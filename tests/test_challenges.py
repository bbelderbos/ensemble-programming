import json

import pytest

from challenges import Challenge, load_challenges
from scripts.export_challenges import export, to_challenge


def bite(**overrides):
    fields = {
        "title": "Sum n numbers",
        "slug": "sum-n-numbers",
        "level": "Beginner",
        "description": "<p>Sum them</p>",
        "filename": "summing",
        "template_code": "def sum_numbers(numbers=None):\r\n    pass\r\n",
        "tests": "from summing import sum_numbers\r\n",
        "solution": "SECRET",
        "free": True,
        "published": True,
        "hide_tests": False,
    }
    return {"model": "bites.bite", "pk": 1, "fields": fields | overrides}


def test_free_bite_becomes_a_challenge_without_its_solution():
    challenge = to_challenge(bite()["fields"])

    assert challenge == Challenge(
        slug="sum-n-numbers",
        title="Sum n numbers",
        level="Beginner",
        description="<p>Sum them</p>",
        module="summing",
        template_code="def sum_numbers(numbers=None):\n    pass\n",
        tests="from summing import sum_numbers\n",
    )
    assert "SECRET" not in challenge.model_dump_json()


def test_module_name_drops_a_py_extension():
    assert to_challenge(bite(filename="regex.py")["fields"]).module == "regex"


@pytest.mark.parametrize(
    "overrides",
    [
        {"free": False},
        {"published": False},
        {"hide_tests": True},
        {"template_code": "from urllib.request import urlretrieve\n"},
        {"tests": "from fastapi.testclient import TestClient\n"},
        {"template_code": "from summing import sum_numbers\n\ndef test_sum(): ...\n"},
    ],
    ids=[
        "paid",
        "unpublished",
        "hidden-tests",
        "downloads-data",
        "needs-fastapi",
        "you-write-the-tests",
    ],
)
def test_bites_that_cannot_run_here_are_skipped(overrides):
    assert to_challenge(bite(**overrides)["fields"]) is None


def test_export_keeps_only_bites_ordered_by_level(tmp_path):
    catalog = [
        {"model": "bites.tag", "pk": 1, "fields": {"name": "x", "slug": "x"}},
        bite(title="Zeta", slug="zeta", level="Intermediate"),
        bite(title="Beta", slug="beta", level="Intro"),
        bite(title="Alpha", slug="alpha", level="Beginner"),
    ]
    source, target = tmp_path / "catalog.json", tmp_path / "challenges.json"
    source.write_text(json.dumps(catalog))

    export(source, target)

    assert [c.slug for c in load_challenges(target).values()] == [
        "beta",
        "alpha",
        "zeta",
    ]
