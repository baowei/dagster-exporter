import os
import time
import requests
import threading
from prometheus_client import generate_latest, REGISTRY
from prometheus_client.core import GaugeMetricFamily
from http.server import BaseHTTPRequestHandler, HTTPServer

# Configuration
DAGSTER_ENDPOINT = os.getenv('GRAPHQL_ENDPOINT', 'https://default-dagster.example.com/graphql')
QUERY_INTERVAL = int(os.getenv('QUERY_INTERVAL', 300))
SLEEP_INTERVAL = int(os.getenv('SLEEP_INTERVAL', 60))
# Program directory path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TIMESTAMP_FILE = os.path.join(BASE_DIR, '.cache', 'dagster_timestamp.states')

# Ensure the cache directory exists
os.makedirs(os.path.dirname(TIMESTAMP_FILE), exist_ok=True)

# GraphQL Query
RUNS_QUERY = """
query FilteredRunsQuery($after: Float!, $before: Float!) {
  runsOrError(filter: {statuses: [SUCCESS,FAILURE],updatedAfter: $after, createdBefore: $before}) {
    __typename
    ... on Runs {
      results {
        runId
        jobName
        status
        startTime
        endTime
      }
    }
  }
}
"""

# Status Mapping
STATUS_MAPPING = {
    "SUCCESS": 1,
    "FAILURE": 0,
    "STARTED": 2,
    "QUEUED": 3,
    "CANCELLED": 4,
    "UNKNOWN": -1
}


class DagsterCollector:
    def collect(self):
        start_time, end_time = self.get_last_timestamp()
        runs_data = self.fetch_runs(start_time, end_time)
        if runs_data and runs_data.get('data'):
            for run in runs_data['data']['runsOrError']['results']:
                run_id = run['runId']
                job_name = run['jobName']
                status = run['status']
                start_time = run['startTime']
                end_time = run['endTime']
                duration = (end_time - start_time) if end_time and start_time else 0

                status_value = STATUS_MAPPING.get(status, STATUS_MAPPING["UNKNOWN"])

                yield self.create_gauge_metric('dagster_run_status', 'Status of Dagster run', run_id, job_name,
                                               status_value)
                yield self.create_gauge_metric('dagster_run_duration', 'Duration of Dagster run', run_id, job_name,
                                               duration)

    def fetch_runs(self, start_time, end_time):
        variables = {
            "after": start_time,
            "before": end_time
        }
        try:
            response = requests.post(DAGSTER_ENDPOINT, json={'query': RUNS_QUERY, 'variables': variables})
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Error fetching runs: {e}")
            return None

    def create_gauge_metric(self, name, documentation, run_id, job_name, value):
        metric = GaugeMetricFamily(name, documentation, labels=['run_id', 'job_name'])
        metric.add_metric([run_id, job_name], value)
        return metric

    def get_last_timestamp(self):
        current_time = time.time()
        if not os.path.exists(TIMESTAMP_FILE):
            start_time = current_time - QUERY_INTERVAL
            end_time = current_time
            self.update_timestamp(start_time, end_time)
            return start_time, end_time
        else:
            with open(TIMESTAMP_FILE, 'r') as f:
                content = f.read().strip()
                start_time_str, end_time_str = content.split()
                start_time = float(start_time_str)
                end_time = float(end_time_str)

                if current_time - end_time > 120:
                    self.update_timestamp(end_time, current_time)
                return start_time, end_time

    def update_timestamp(self, start_time, end_time):
        with open(TIMESTAMP_FILE, 'w') as f:
            f.write(f"{start_time} {end_time}")


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/metrics':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain; version=0.0.4')
            self.end_headers()
            self.wfile.write(generate_latest(REGISTRY))
        elif self.path == '/info':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()


def run_server(port):
    server_address = ('', port)
    httpd = HTTPServer(server_address, MetricsHandler)
    print(f"Serving metrics on port {port}...")
    httpd.serve_forever()


if __name__ == "__main__":
    # Start the metrics server in a separate thread
    server_thread = threading.Thread(target=run_server, args=(8000,))
    server_thread.daemon = True
    server_thread.start()

    # Register custom collector
    REGISTRY.register(DagsterCollector())

    while True:
        time.sleep(SLEEP_INTERVAL)
