# Ensemble Programming

A shared Python editor for mob/ensemble programming: the whole team works on one codebase in real time, in timed segments with rotating roles.

[![Demo: Alice and Bob solve FizzBuzz together](assets/demo.png)](assets/demo.mp4)

▶️ [Watch the 1-minute demo](assets/demo.mp4)

## Features

- **Live shared editor**: every keystroke streams to everyone in the session. Only the driver can type.
- **Rotating roles**: driver, navigator and timekeeper rotate each segment, so the navigator drives next. With two people the navigator also keeps time.
- **Timed segments with a debrief**: segments last 5 minutes. When time is up, roles rotate and the team takes a break until the timekeeper starts the next segment.
- **Observers**: uncheck "Take part in the rotation" when joining to sit in and watch without taking a turn.
- **Run code in the browser**: Python runs client-side via [Pyodide](https://pyodide.org) (Python 3.14 on WebAssembly), so the server never executes user code.

## How it works

FastAPI serves the pages and two WebSocket channels per session: one for code, one for the rotation (roles, segment timer, who's watching). Redis holds live session state, and the code is flushed to SQLite (SQLModel) every few seconds. The frontend is Jinja templates with htmx and CodeMirror.

Set `ROTATION_SECONDS` in `.env` to change the segment length (default 300).

## Quickstart

```bash
uv sync
cp .env-template .env
docker run -d --name redis -p 6379:6379 redis
uv run fastapi dev main.py
```

Open `localhost:8000`, create a session, then open the session link in a second browser to join. The timekeeper presses **Start segment** to begin.

## Tests

```bash
uv run pytest -q
```

Tests use fakeredis, so they don't need a running Redis.

### Manual test: running code

1. Open `localhost:8000`, create a session, enter a name.
2. Type `x = 1; print("hi", x)` and click **Run Code** → Stdout shows `hi 1`. The first run takes a few seconds while Pyodide (~10 MB) downloads; later runs are instant.
3. Replace the code with `print(x)` and run → Stderr shows `NameError`, because each run starts with a fresh namespace.
4. Run `import sys; print("oops", file=sys.stderr)` → `oops` appears under Stderr.
5. Run `1/0` → Stderr shows a `ZeroDivisionError` traceback and the button is clickable again.
6. Open the session link in a 2nd browser, run code there → output only appears in that browser (execution is local to each participant).

## Re-recording the demo

The demo is scripted with Playwright: two browsers play Alice and Bob (a third, unrecorded one joins as observer Carol), and ffmpeg stitches them side by side with captions. It uses 18-second segments so the rotation fits in the video.

```bash
ROTATION_SECONDS=18 uv run uvicorn main:app --port 8765   # in another terminal
uv run --with playwright python assets/record_demo.py
```

Needs ffmpeg and a Playwright Chromium (`uvx playwright install chromium`). Writes `assets/demo.mp4`.
