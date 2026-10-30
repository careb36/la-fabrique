FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="/root/.local/bin:$PATH"

# Copy dependency manifests first for layer caching — code changes won't
# invalidate the pip install layer as long as these files don't change.
COPY pyproject.toml poetry.lock* /app/

# Install only production dependencies; skip dev extras and the root package
# itself (no installable package here, just application code).
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --no-root --only main

# Copy only the application source trees needed at runtime.
# Avoids copying .git, node_modules, frontend/, docs/, tests/, etc.
COPY app/     /app/app/
COPY llm/     /app/llm/
COPY agents/  /app/agents/
COPY memory/  /app/memory/
COPY telemetry.py /app/telemetry.py

# Run as an unprivileged user, never as root: a flaw in the app then cannot
# rewrite the image or reach what root reaches on a shared volume.
RUN useradd --create-home --uid 1000 --user-group app
# The audit log volume (factory-logs) and the generated builds are written at
# run time; a named volume mounted on an existing directory takes its owner.
RUN mkdir -p /app/.factory/logs /workspace/builds && chown -R app:app /app/.factory /workspace
USER app

EXPOSE 8000

# /app      — repo root (pyproject.toml, poetry.lock live here)
# /app/app  — FastAPI application package (routers, models, services, …)
ENV PYTHONPATH="/app:/app/app"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
