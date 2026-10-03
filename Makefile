.PHONY: install dev redis test lint check deploy logs status demo challenges

install:
	uv sync
	uv run playwright install chromium

redis:
	redis-server --daemonize yes

dev:
	uv run fastapi dev main.py

test:
	uv run pytest -q

lint:
	uv run ruff format .
	uv run ruff check --fix .
	uv run ty check .

check: lint test

# Fly commands use FLY_API_TOKEN when set, else your logged-in account
deploy:
	fly deploy --ha=false

logs:
	fly logs

status:
	fly status

# Records static/demo.mp4; the app must run with short segments
demo:
	@echo "Run first: ROTATION_SECONDS=18 uv run uvicorn main:app --port 8765"
	uv run --with playwright python assets/record_demo.py

# Re-export free exercises from the platform's catalog fixture
CATALOG ?= ../pybitesplatform/bites/fixtures/bites_catalog.json
challenges:
	uv run python -m scripts.export_challenges $(CATALOG)
