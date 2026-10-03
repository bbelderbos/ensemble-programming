import json

import pytest
from fastapi.testclient import TestClient

import main
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


def runnable(fields: dict) -> Challenge:
    challenge = to_challenge(fields)
    assert challenge is not None
    return challenge


def test_module_name_drops_a_py_extension():
    assert runnable(bite(filename="regex.py")["fields"]).module == "regex"


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


@pytest.fixture
def client():
    with TestClient(main.app) as client:
        yield client


def start(client, **form):
    response = client.post("/new-session", data=form)
    return response.headers.get("HX-Redirect"), response


def test_landing_page_offers_the_challenges(client):
    page = client.get("/").text

    for challenge in main.CHALLENGES.values():
        assert challenge.title in page


def test_landing_page_plays_the_demo(client):
    page = client.get("/").text

    assert "/static/demo.mp4" in page
    assert client.get("/static/demo.mp4").status_code == 200


def test_starting_from_a_challenge_seeds_the_editor_and_shows_the_tests(client):
    challenge = main.CHALLENGES["sum-n-numbers"]

    url, _ = start(client, goal=challenge.title, challenge=challenge.slug)
    session_id = url.rsplit("/", 1)[1]
    page = client.get(url).text

    assert (
        main.redis_client.get(main.key(session_id, "code")) == challenge.template_code
    )
    assert "def test_sum_numbers_default_args" in page
    assert "the sum of a list" in page


def test_unknown_challenge_is_rejected(client):
    _, response = start(client, goal="x", challenge="does-not-exist")

    assert response.status_code == 400


def test_plain_session_has_no_challenge(client):
    url, _ = start(client, goal="Refactor billing")

    assert "def test_" not in client.get(url).text


def test_bites_using_pydantic_are_kept_since_pyodide_ships_it():
    fields = bite(template_code="from pydantic import BaseModel\n")["fields"]

    assert to_challenge(fields) is not None


TEMPLATE = "def uppercase_vowels(text: str) -> str:\n    pass\n"


@pytest.mark.parametrize(
    ("tests", "expected_call"),
    [
        (
            'def test_a():\n    assert uppercase_vowels("Hi you") == "hI yOU"\n',
            'uppercase_vowels("Hi you")',
        ),
        (
            'def test_a(text):\n    uppercase_vowels(text)\n    uppercase_vowels(text="ok")\n',
            'uppercase_vowels(text="ok")',
        ),
    ],
    ids=["first-literal-call", "skips-calls-with-variables"],
)
def test_starter_code_gets_a_runnable_example_from_the_tests(tests, expected_call):
    template = runnable(
        bite(template_code=TEMPLATE, tests=tests)["fields"]
    ).template_code

    assert (
        template
        == TEMPLATE + f'\n\nif __name__ == "__main__":\n    print({expected_call})\n'
    )


@pytest.mark.parametrize(
    "template",
    [TEMPLATE, 'def ask():\n    return input("Color? ")\n'],
    ids=["no-literal-call", "reads-input"],
)
def test_no_example_when_none_is_safe(template):
    tests = "def test_a(x):\n    assert uppercase_vowels(x)\n    ask()\n"

    assert (
        runnable(bite(template_code=template, tests=tests)["fields"]).template_code
        == template
    )


def test_no_example_when_the_tests_fake_user_input():
    tests = '@patch("builtins.input", side_effect=["red"])\ndef test_a(i):\n    uppercase_vowels()\n'
    fields = bite(template_code=TEMPLATE, tests=tests)["fields"]

    assert runnable(fields).template_code == TEMPLATE


def test_existing_main_block_is_left_alone():
    template = TEMPLATE + '\nif __name__ == "__main__":\n    uppercase_vowels("x")\n'
    tests = 'def test_a():\n    assert uppercase_vowels("Hi")\n'

    assert (
        runnable(bite(template_code=template, tests=tests)["fields"]).template_code
        == template
    )
