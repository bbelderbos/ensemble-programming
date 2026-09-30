# Ensemble Programming

Building a tool to work as a team on a single codebase.

Uses FastAPI, sqlmodel, websockets, redis and some htmx for the frontend.

Code runs in each participant's browser via [Pyodide](https://pyodide.org) (Python 3.14 compiled to WebAssembly), so the server never executes user code.

## Setup + run

```bash
$ uv sync
$ cp .env-template .env
$ docker run -d --name redis -p 6379:6379 redis
$ uv run fastapi dev main.py
# go to localhost:8000, create a session and join in from 2nd browser using session link
```

## Manual test: running code

1. Open `localhost:8000`, create a session, enter a name.
2. Type `x = 1; print("hi", x)` and click **Run Code** → Stdout shows `hi 1`. The first run takes a few seconds while Pyodide (~10 MB) downloads; later runs are instant.
3. Replace the code with `print(x)` and run → Stderr shows `NameError`, because each run starts with a fresh namespace.
4. Run `import sys; print("oops", file=sys.stderr)` → `oops` appears under Stderr.
5. Run `1/0` → Stderr shows a `ZeroDivisionError` traceback and the button is clickable again.
6. Open the session link in a 2nd browser, run code there → output only appears in that browser (execution is local to each participant).
