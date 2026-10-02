import ast
import json
import re
import sys
from pathlib import Path

from challenges import CHALLENGES_FILE, Challenge

LEVEL_ORDER = ["Newbie", "Intro", "Beginner", "Intermediate", "Advanced"]
# Pyodide has no network access to data files, and FastAPI is not one of its packages
UNSUPPORTED = re.compile(r"urlretrieve|urlopen|import requests|fastapi")


def is_literal(node: ast.expr) -> bool:
    try:
        ast.literal_eval(node)
    except ValueError:
        return False
    return True


def with_example_call(template: str, tests: str) -> str:
    """Append a __main__ call copied from the tests so Run Code shows output."""
    # input() would pop up a browser prompt, and an existing __main__ already shows output
    if "input(" in template or "builtins.input" in tests or "__main__" in template:
        return template
    try:
        functions = {
            node.name
            for node in ast.parse(template).body
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
        }
        calls = sorted(
            (node for node in ast.walk(ast.parse(tests)) if isinstance(node, ast.Call)),
            key=lambda node: (node.lineno, node.col_offset),
        )
    except SyntaxError:
        return template

    for call in calls:
        arguments = [*call.args, *(keyword.value for keyword in call.keywords)]
        if (
            isinstance(call.func, ast.Name)
            and call.func.id in functions
            and call.lineno == call.end_lineno
            and all(is_literal(argument) for argument in arguments)
        ):
            example = ast.get_source_segment(tests, call)
            return f'{template}\n\nif __name__ == "__main__":\n    print({example})\n'
    return template


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
    template = fields["template_code"].replace("\r\n", "\n")
    tests = fields["tests"].replace("\r\n", "\n")
    return Challenge(
        slug=fields["slug"],
        title=fields["title"],
        level=fields["level"],
        description=fields["description"].replace("\r\n", "\n"),
        module=module,
        template_code=with_example_call(template, tests),
        tests=tests,
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
