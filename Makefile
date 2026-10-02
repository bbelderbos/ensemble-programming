.PHONY: install dev redis test lint check deploy logs status demo

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

check: lint test

# Fly commands use FLY_API_TOKEN when set, else your logged-in account
deploy:
	fly deploy --ha=false

logs:
	fly logs

status:
	fly status

# Records assets/demo.mp4; the app must run with short segments
demo:
	@echo "Run first: ROTATION_SECONDS=18 uv run uvicorn main:app --port 8765"
	uv run --with playwright python assets/record_demo.py
