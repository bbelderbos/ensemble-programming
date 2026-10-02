import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

CHALLENGES_FILE = Path(__file__).parent / "challenges.json"


class Challenge(BaseModel):
    model_config = ConfigDict(frozen=True)

    slug: str
    title: str
    level: str
    description: str
    module: str
    template_code: str
    tests: str


def load_challenges(path: Path = CHALLENGES_FILE) -> dict[str, Challenge]:
    """Challenges keyed by slug, in the order they were exported."""
    challenges = (Challenge(**item) for item in json.loads(path.read_text()))
    return {challenge.slug: challenge for challenge in challenges}
