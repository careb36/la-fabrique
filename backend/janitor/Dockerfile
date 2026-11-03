FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y libpq-dev gcc && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir psycopg2-binary python-dotenv

COPY backend/janitor/main.py .

# Run as an unprivileged user, never as root: a flaw in the app then cannot
# rewrite the image or reach what root reaches on a shared volume.
RUN useradd --create-home --uid 1000 --user-group app
USER app

CMD ["python", "main.py"]
