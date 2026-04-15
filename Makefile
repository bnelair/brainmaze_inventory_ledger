.PHONY: help build up down logs shell clean install run lint

help:            ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*##' Makefile | awk 'BEGIN{FS=":.*##"}{printf "  \033[36m%-14s\033[0m %s\n",$$1,$$2}'

# ── Local development ─────────────────────────────────────────────────────────

install:         ## Install Python dependencies locally
	pip install -r requirements.txt

run:             ## Run Streamlit directly (no Docker)
	DATA_DIR=./inventory_data REPORTS_DIR=./reports \
	streamlit run src/app.py

lint:            ## Lint Python source files
	python -m py_compile src/inventory.py src/reports.py src/git_manager.py src/app.py \
	  && echo "Syntax OK"

# ── Docker ───────────────────────────────────────────────────────────────────

build:           ## Build the Docker image
	docker compose build

up:              ## Start the application in the background
	docker compose up -d

down:            ## Stop and remove containers
	docker compose down

logs:            ## Tail application logs
	docker compose logs -f

shell:           ## Open a shell inside the running container
	docker compose exec app bash

restart:         ## Restart the application container
	docker compose restart app

# ── Utilities ────────────────────────────────────────────────────────────────

clean:           ## Remove containers, volumes, and local artefacts
	docker compose down -v
	rm -rf reports/*.pdf __pycache__ src/__pycache__
