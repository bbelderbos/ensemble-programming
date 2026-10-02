import json
import re
import sys
from pathlib import Path

from challenges import CHALLENGES_FILE, Challenge

LEVEL_ORDER = ["Newbie", "Intro", "Beginner", "Intermediate", "Advanced"]
# Pyodide has no network access to data files, and the FastAPI series needs extra packages
UNSUPPORTED = re.compile(r"urlretrieve|urlopen|import requests|fastapi|pydantic")


def to_challenge(fields: dict) -> Challenge | None:
    source = fields["template_code"] + fields["tests"]
    module = fields["filename"].removesuffix(".py")
    # Starter code importing its own module means you write the tests (graded by mutation testing)
    writes_tests = f"from {module} import" in fields["template_code"]
    runnable = (
        fields["free"]
        and fields["published"]
        and not fields["hide_tests"]
        and not UNSUPPORTED.search(source)
        and not writes_tests
    )
    if not runnable:
        return None
    return Challenge(
        slug=fields["slug"],
        title=fields["title"],
        level=fields["level"],
        description=fields["description"].replace("\r\n", "\n"),
        module=module,
        template_code=fields["template_code"].replace("\r\n", "\n"),
        tests=fields["tests"].replace("\r\n", "\n"),
    )


def export(catalog: Path, target: Path = CHALLENGES_FILE) -> int:
    bites = (
        to_challenge(item["fields"])
        for item in json.loads(catalog.read_text())
        if item["model"] == "bites.bite"
    )
    challenges = sorted(
        (c for c in bites if c),
        key=lambda c: (LEVEL_ORDER.index(c.level), c.title),
    )
    target.write_text(json.dumps([c.model_dump() for c in challenges], indent=2) + "\n")
    return len(challenges)


if __name__ == "__main__":
    print(f"Exported {export(Path(sys.argv[1]))} challenges")
