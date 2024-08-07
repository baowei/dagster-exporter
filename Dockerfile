FROM python:3.12.3-bullseye as base

RUN apt-get update && rm -rf /var/lib/apt/lists/*
WORKDIR /app

FROM base as builder

COPY requirements.txt requirements.txt
RUN python -m venv .venv

RUN .venv/bin/pip install -r requirements.txt

FROM base as final

COPY dagster-exporter.py /app/dagster-exporter.py
COPY --from=builder /app/.venv /app/.venv

EXPOSE 8000

ENV PATH="/app/.venv/bin:${PATH}"

ENTRYPOINT ["python","/app/dagster-exporter.py"]