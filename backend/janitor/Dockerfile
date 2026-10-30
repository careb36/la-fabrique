FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y libpq-dev gcc && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir psycopg2-binary python-dotenv

COPY backend/janitor/main.py .

CMD ["python", "main.py"]
