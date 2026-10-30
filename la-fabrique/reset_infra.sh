#!/usr/bin/env bash

# Reinicia toda la infraestructura Docker desde cero.
set -euo pipefail

SCRIPT_DIR="$(cd "$(/usr/bin/dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v docker >/dev/null 2>&1; then
  DOCKER_DESKTOP_BIN="/Applications/Docker.app/Contents/Resources/bin"
  if [[ -d "$DOCKER_DESKTOP_BIN" ]]; then
    export PATH="$DOCKER_DESKTOP_BIN:$PATH"
  fi
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: docker no esta disponible en PATH." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Error: Docker Desktop no esta corriendo o no responde." >&2
  exit 1
fi

echo "[1/6] Deteniendo contenedores y destruyendo volumenes, redes y huerfanos..."
docker compose down -v --remove-orphans

echo "[2/6] Limpiando basura de Docker (imagenes colgantes y redes sin uso)..."
docker system prune -f

echo "[3/6] Reconstruyendo imagenes desde cero (sin cache)..."
docker compose build --no-cache

echo "[4/6] Levantando toda la infraestructura en segundo plano..."
docker compose up -d

echo "[5/6] Esperando 5 segundos para que los servicios arranquen..."
sleep 5

echo "[6/6] Estado actual de los contenedores:"
docker compose ps

echo
echo "Sistema limpio y corriendo."
echo "Frontend: http://localhost:5173"
echo "Backend API: http://localhost:8000/docs"