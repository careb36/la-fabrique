.PHONY: setup install dev-backend dev-frontend dev-all clean

# Variables
PYTHON_VERSION = 3.11
NODE_VERSION = 24

# Colores para la consola
GREEN  := $(shell tput -Txterm setaf 2)
RESET  := $(shell tput -Txterm sgr0)

setup:
	@echo "$(GREEN)🚀 Configurando el entorno de La Fabrique...$(RESET)"
	@make install

install:
	@echo "$(GREEN)📦 Instalando dependencias del Backend (Poetry)...$(RESET)"
	cd backend && poetry install
	@echo "$(GREEN)📦 Instalando dependencias del Frontend (npm)...$(RESET)"
	cd frontend && npm install
	@echo "$(GREEN)📦 Instalando dependencias del LLM Proxy (Poetry)...$(RESET)"
	cd llm-proxy && poetry install

dev-backend:
	@echo "$(GREEN)🔥 Iniciando Backend (FastAPI)...$(RESET)"
	cd backend && poetry run uvicorn app.main:app --reload --port 8000

dev-llm-proxy:
	@echo "$(GREEN)🤖 Iniciando LLM Proxy (Flask)...$(RESET)"
	cd llm-proxy && poetry run python app.py

dev-frontend:
	@echo "$(GREEN)🎨 Iniciando Frontend (React/Vite)...$(RESET)"
	cd frontend && npm run dev

dev-all:
	@echo "$(GREEN)🚀 Levantando todo el ecosistema (Requiere tmux o similar para ver logs)...$(RESET)"
	@make -j 3 dev-backend dev-llm-proxy dev-frontend

clean:
	@echo "$(GREEN)🧹 Limpiando cachés y entornos...$(RESET)"
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name "node_modules" -exec rm -rf {} +
	@echo "$(GREEN)✨ Entorno limpio.$(RESET)"
