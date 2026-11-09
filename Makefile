# FMEA Platform — developer convenience targets
#
# Requires: Python 3.11+, Node 18+, npm, make (Git Bash / WSL on Windows)
#
# Usage:
#   make dev          — start FastAPI + Vite dev server (two terminals)
#   make api          — start FastAPI only
#   make frontend     — start Vite dev server only
#   make test         — run all Python tests
#   make build        — production build of React frontend
#   make bench        — scan the benchmark repositories (spends real money; see benchmarks/run.py)
#   make bench-report — score stored benchmark runs and print the comparison table

.PHONY: dev api frontend test build bench bench-report

# Start both API and frontend dev servers (requires two terminals or a process manager)
dev:
	@echo "Starting FastAPI on :8000 and React dev server on :5173"
	@echo "Run each command in a separate terminal:"
	@echo "  make api"
	@echo "  make frontend"

api:
	uvicorn api.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

test:
	python -m pytest tests/ -v

build:
	cd frontend && npm run build

# Extra flags go in ARGS, e.g. make bench ARGS="--model mistral-large-4 --label baseline --runs 3"
bench:
	python -m benchmarks.run $(ARGS)

bench-report:
	python -m benchmarks.report $(ARGS)
