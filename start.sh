#!/bin/sh
set -e
# Redis lives in the same machine; its snapshot goes on the volume next to SQLite
redis-server --daemonize yes --dir /data --save 60 1
exec /app/.venv/bin/fastapi run main.py --port 8000
