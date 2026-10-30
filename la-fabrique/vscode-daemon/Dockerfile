FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir nats-py==2.3.1

COPY daemon.py /app/daemon.py

CMD ["python", "/app/daemon.py"]
