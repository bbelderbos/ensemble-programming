import asyncio
import json
import math
import time
import uuid
from dataclasses import asdict

import redis
from decouple import config
from fastapi import (
    FastAPI,
    Form,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Field, Session, SQLModel, create_engine, select

from challenges import load_challenges
from rotation import Roles, assign_roles

DATABASE_URL = config("DATABASE_URL")
REDIS_URL = config("REDIS_URL", default="redis://localhost:6379")

engine = create_engine(DATABASE_URL, echo=True)
templates = Jinja2Templates(directory="templates")

redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)

CHALLENGES = load_challenges()
ROTATION_SECONDS = config("ROTATION_SECONDS", default=300, cast=int)


class SessionModel(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    goal: str
    code: str = ""


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, session_id: str, websocket: WebSocket):
        """Accept WebSocket connections and track active clients."""
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = []
        self.active_connections[session_id].append(websocket)

    def disconnect(self, session_id: str, websocket: WebSocket):
        """Remove disconnected clients from active connections."""
        connections = self.active_connections.get(session_id, [])
        if websocket in connections:
            connections.remove(websocket)
        if not connections and session_id in self.active_connections:
            del self.active_connections[session_id]

    async def broadcast(
        self, session_id: str, message: str, exclude: WebSocket | None = None
    ):
        """Send message to all connected clients in a session."""
        for connection in list(self.active_connections.get(session_id, [])):
            if connection is exclude:
                continue
            try:
                await connection.send_text(message)
            except (WebSocketDisconnect, RuntimeError):
                # Closed tab whose disconnect isn't processed yet; skip it
                self.disconnect(session_id, connection)


manager = ConnectionManager()
rotation_manager = ConnectionManager()
# Keeps a reference so running segment timers are not garbage collected
segment_timers: dict[str, asyncio.Task] = {}

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
def init_db():
    SQLModel.metadata.create_all(engine)


@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse(
        "index.html", {"request": request, "challenges": CHALLENGES.values()}
    )


@app.post("/new-session")
async def new_session(goal: str = Form(...), challenge: str | None = Form(None)):
    """Creates a new coding session, optionally starting from a challenge."""
    if challenge and challenge not in CHALLENGES:
        raise HTTPException(status_code=400, detail=f"Unknown challenge {challenge}")

    with Session(engine) as session:
        new_session = SessionModel(goal=goal)
        session.add(new_session)
        session.commit()
        session_id = new_session.id

    if challenge:
        redis_client.set(key(session_id, "challenge"), challenge)
        redis_client.set(key(session_id, "code"), CHALLENGES[challenge].template_code)
    return JSONResponse(content={}, headers={"HX-Redirect": f"/session/{session_id}"})


@app.get("/session/{session_id}")
async def session_page(request: Request, session_id: str):
    """Returns the session page with real-time code editor."""
    slug = redis_client.get(key(session_id, "challenge"))
    return templates.TemplateResponse(
        "session.html",
        {
            "request": request,
            "session_id": session_id,
            "rotation_seconds": ROTATION_SECONDS,
            "challenge": CHALLENGES.get(slug) if slug else None,
        },
    )


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(session_id: str, websocket: WebSocket):
    """Handles real-time collaborative editing and typing notifications via WebSockets."""
    await manager.connect(session_id, websocket)
    if code := redis_client.get(key(session_id, "code")):
        await websocket.send_text(json.dumps({"type": "code", "content": code}))

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            if message.get("type") == "code":
                if message.get("username") != current_roles(session_id).driver:
                    continue
                redis_client.set(key(session_id, "code"), message["content"])

                await manager.broadcast(
                    session_id,
                    json.dumps({"type": "code", "content": message["content"]}),
                    # A stale echo would overwrite the sender's newer edits
                    exclude=websocket,
                )

            elif message.get("type") == "typing":
                await manager.broadcast(
                    session_id,
                    json.dumps({"type": "typing", "username": message["username"]}),
                )

            elif message.get("type") == "stopped_typing":
                await manager.broadcast(
                    session_id,
                    json.dumps(
                        {"type": "stopped_typing", "username": message["username"]}
                    ),
                )

    except WebSocketDisconnect:
        manager.disconnect(session_id, websocket)


def key(session_id: str, name: str) -> str:
    return f"session:{session_id}:{name}"


def current_roles(session_id: str) -> Roles:
    participants = redis_client.lrange(key(session_id, "participants"), 0, -1)
    segment = int(redis_client.get(key(session_id, "segment")) or 0)
    return assign_roles(participants, segment)


def rotation_state(session_id: str) -> dict:
    ends_at = redis_client.get(key(session_id, "ends_at"))
    return {
        "type": "rotation",
        "participants": redis_client.lrange(key(session_id, "participants"), 0, -1),
        "observers": sorted(redis_client.smembers(key(session_id, "observers"))),
        **asdict(current_roles(session_id)),
        # None means the team is on a debrief break between segments
        "remaining": math.ceil(float(ends_at) - time.time()) if ends_at else None,
    }


async def broadcast_rotation(session_id: str) -> None:
    await rotation_manager.broadcast(session_id, json.dumps(rotation_state(session_id)))


async def end_segment_after(session_id: str, seconds: float) -> None:
    await asyncio.sleep(seconds)
    # Zero deletes means another path already ended this segment
    if redis_client.delete(key(session_id, "ends_at")):
        redis_client.incr(key(session_id, "segment"))
        await broadcast_rotation(session_id)


async def resume_segment(session_id: str) -> None:
    """Re-arm a segment whose timer task was lost, e.g. by a server restart."""
    ends_at = redis_client.get(key(session_id, "ends_at"))
    timer = segment_timers.get(session_id)
    if not ends_at or (timer and not timer.done()):
        return
    remaining = float(ends_at) - time.time()
    if remaining <= 0:
        await end_segment_after(session_id, 0)
    else:
        segment_timers[session_id] = asyncio.create_task(
            end_segment_after(session_id, remaining)
        )


def start_segment(session_id: str, username: str) -> bool:
    running = redis_client.exists(key(session_id, "ends_at"))
    if running or username != current_roles(session_id).timekeeper:
        return False
    redis_client.set(key(session_id, "ends_at"), time.time() + ROTATION_SECONDS)
    segment_timers[session_id] = asyncio.create_task(
        end_segment_after(session_id, ROTATION_SECONDS)
    )
    return True


@app.websocket("/ws/rotation/{session_id}")
async def websocket_rotation(session_id: str, websocket: WebSocket):
    """Tracks who drives, navigates and keeps time, and runs the segment timer."""
    await rotation_manager.connect(session_id, websocket)
    await resume_segment(session_id)
    username = None

    try:
        while True:
            message = json.loads(await websocket.receive_text())

            if message["type"] == "join":
                username = message["username"]
                leave_rotation(session_id, username)
                if message.get("participate"):
                    redis_client.rpush(key(session_id, "participants"), username)
                else:
                    redis_client.sadd(key(session_id, "observers"), username)

            elif message["type"] == "start":
                if not start_segment(session_id, message["username"]):
                    continue

            await broadcast_rotation(session_id)

    except WebSocketDisconnect:
        rotation_manager.disconnect(session_id, websocket)
        if username:
            leave_rotation(session_id, username)
            await broadcast_rotation(session_id)


def leave_rotation(session_id: str, username: str) -> None:
    redis_client.srem(key(session_id, "observers"), username)
    participants = redis_client.lrange(key(session_id, "participants"), 0, -1)
    if username not in participants:
        return

    driver_seat = int(redis_client.get(key(session_id, "segment")) or 0) % len(
        participants
    )
    leaver_seat = participants.index(username)
    remaining = len(participants) - 1
    # Keep the same driver unless the driver left, then the navigator takes over
    if leaver_seat < driver_seat:
        driver_seat -= 1
    new_segment = driver_seat % remaining if remaining else 0

    redis_client.lrem(key(session_id, "participants"), 0, username)
    redis_client.set(key(session_id, "segment"), new_segment)


async def save_code_to_db():
    """Periodically saves Redis/in-memory code updates to the database only if changes exist."""
    while True:
        await asyncio.sleep(5)

        with Session(engine) as session:
            stmt = select(SessionModel)
            sessions = session.exec(stmt).all()
            any_updates = False

            for session_obj in sessions:
                latest_code = redis_client.get(f"session:{session_obj.id}:code")

                if latest_code and latest_code != session_obj.code:
                    session_obj.code = latest_code
                    session.add(session_obj)
                    any_updates = True

            if any_updates:
                session.commit()


@app.on_event("startup")
async def start_background_tasks():
    """Start the Redis-to-DB sync process only if storage is available."""
    asyncio.create_task(save_code_to_db())
