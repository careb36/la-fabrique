FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir nats-py==2.3.1

COPY daemon.py nats_scope.py shell_exec.py /app/

# Run as an unprivileged user, never as root: a flaw in the app then cannot
# rewrite the image or reach what root reaches on a shared volume.
RUN useradd --create-home --uid 1000 --user-group app
# docker-compose runs it as the owner of the mounted projects folder
# (DAEMON_UID/DAEMON_GID), so the files it writes there stay yours.
USER app

CMD ["python", "/app/daemon.py"]
