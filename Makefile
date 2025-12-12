.PHONY: help install install-backend install-frontend dev dev-backend dev-frontend dev-all build clean

# Default target
help:
	@echo "Available commands:"
	@echo "  make install          - Install all dependencies (backend + frontend)"
	@echo "  make install-backend  - Install backend dependencies"
	@echo "  make install-frontend - Install frontend dependencies"
	@echo "  make dev-backend      - Run backend server (port 8000)"
	@echo "  make dev-frontend     - Run frontend server (port 5173)"
	@echo "  make dev-all          - Run both backend and frontend servers"
	@echo "  make build            - Build frontend for production"
	@echo "  make clean            - Clean build artifacts"

# Install dependencies
install: install-backend install-frontend

install-backend:
	@echo "📦 Installing backend dependencies..."
	cd backend && uv sync

install-frontend:
	@echo "📦 Installing frontend dependencies..."
	cd frontend && npm install

# Development servers
dev-backend:
	@echo "🚀 Starting backend server on http://localhost:8000"
	cd backend && uv run fastapi dev app/main.py --host 0.0.0.0 --port 8000

dev-frontend:
	@echo "🚀 Starting frontend server on http://localhost:5173"
	cd frontend && npm run dev

# Run both servers concurrently
dev-all:
	@echo "🚀 Starting both backend and frontend servers..."
	@echo "   Backend: http://localhost:8000"
	@echo "   Frontend: http://localhost:5173"
	@trap 'kill 0' EXIT; \
	cd backend && uv run fastapi dev app/main.py --host 0.0.0.0 --port 8000 & \
	cd frontend && npm run dev & \
	wait

# Build frontend for production
build:
	@echo "🏗️  Building frontend for production..."
	cd frontend && npm run build

# Clean build artifacts
clean:
	@echo "🧹 Cleaning build artifacts..."
	rm -rf frontend/dist
	rm -rf frontend/node_modules/.vite
	rm -rf backend/__pycache__
	rm -rf backend/app/__pycache__
	find . -type d -name __pycache__ -exec rm -r {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

