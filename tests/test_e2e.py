import re

import pytest
from playwright.sync_api import BrowserContext, Page, expect

import main

pytestmark = pytest.mark.e2e


def create_session(context: BrowserContext, base_url: str) -> Page:
    page = context.new_page()
    page.goto(base_url)
    page.fill("input[name=goal]", "FizzBuzz")
    page.click("text=Create Session")
    page.wait_for_url(re.compile("/session/"))
    return page


def join(page: Page, name: str, participate: bool = True) -> Page:
    page.fill("#username-input", name)
    if not participate:
        page.uncheck("#rotation-opt-in")
    page.click("text=Join")
    return page


def open_and_join(context: BrowserContext, url: str, name: str, **kwargs) -> Page:
    page = context.new_page()
    page.goto(url)
    return join(page, name, **kwargs)


def is_read_only(page: Page) -> bool:
    return page.evaluate("editor.getOption('readOnly')")


def test_roles_rotate_and_only_the_driver_types(live_server, context, monkeypatch):
    monkeypatch.setattr(main, "ROTATION_SECONDS", 3)
    alice = join(create_session(context, live_server), "Alice")
    bob = open_and_join(context, alice.url, "Bob")
    carol = open_and_join(context, alice.url, "Carol", participate=False)

    expect(alice.locator("#editor-status")).to_have_text("You're driving.")
    expect(bob.locator("#editor-status")).to_have_text("Alice is driving.")
    expect(carol.locator("#editor-status")).to_have_text("Alice is driving.")
    expect(alice.locator("#observer-list")).to_have_text("Carol")
    assert not is_read_only(alice)
    assert is_read_only(bob) and is_read_only(carol)

    # Bob navigates and, with two in the rotation, keeps time
    expect(bob.locator("#start-button")).to_be_visible()
    expect(alice.locator("#start-button")).to_be_hidden()
    expect(carol.locator("#start-button")).to_be_hidden()
    bob.click("#start-button")

    alice.locator(".CodeMirror").click()
    alice.keyboard.type("x = 1")
    expect(bob.locator(".CodeMirror")).to_contain_text("x = 1")
    expect(carol.locator(".CodeMirror")).to_contain_text("x = 1")

    expect(bob.locator("#editor-status")).to_have_text("You're driving.")
    expect(alice.locator("#segment-label")).to_contain_text("Break")
    expect(alice.locator("#start-button")).to_be_visible()
    assert is_read_only(alice)
    assert not is_read_only(bob)


def test_code_runs_in_the_browser(live_server, context):
    alice = join(create_session(context, live_server), "Alice")
    expect(alice.locator("#editor-status")).to_have_text("You're driving.")

    alice.locator(".CodeMirror").click()
    alice.keyboard.type('print("hi", 1 + 1)')
    alice.click("#run-button")

    # First run downloads Pyodide from the CDN
    expect(alice.locator("#output-status")).to_contain_text("Finished", timeout=60_000)
    expect(alice.locator("#stdout")).to_have_text("hi 2")
    expect(alice.locator("#stderr")).to_be_hidden()


def test_errors_show_a_clean_highlighted_traceback(live_server, context):
    alice = join(create_session(context, live_server), "Alice")
    expect(alice.locator("#editor-status")).to_have_text("You're driving.")

    alice.locator(".CodeMirror").click()
    alice.keyboard.type('print("before")\n1/0')
    alice.click("#run-button")

    status = alice.locator("#output-status")
    expect(status).to_contain_text("ZeroDivisionError", timeout=60_000)
    expect(alice.locator("#stdout")).to_have_text("before")
    stderr = alice.locator("#stderr")
    expect(stderr).to_contain_text('File "<editor>", line 2')
    expect(stderr).to_contain_text("1/0")  # the offending source line
    expect(stderr).not_to_contain_text("_pyodide")
    # Pygments wraps tokens in colored spans
    assert stderr.locator("span[style*=color]").count() > 0


SUM_SOLUTION = """def sum_numbers(numbers=None):
    if numbers is None:
        numbers = range(1, 101)
    return sum(numbers)
"""


def test_challenge_tests_run_in_the_browser(live_server, context):
    alice = context.new_page()
    alice.goto(live_server)
    alice.get_by_role("button", name="Sum n numbers").click()
    alice.wait_for_url(re.compile("/session/"))
    join(alice, "Alice")
    expect(alice.locator("#editor-status")).to_have_text("You're driving.")
    expect(alice.locator(".CodeMirror")).to_contain_text("def sum_numbers")

    alice.click("#test-button")
    status = alice.locator("#output-status")
    expect(status).to_contain_text("failed", timeout=90_000)

    alice.evaluate("code => editor.setValue(code)", SUM_SOLUTION)
    alice.click("#test-button")
    expect(status).to_contain_text("2 passed", timeout=30_000)


def test_plain_sessions_have_no_test_button(live_server, context):
    alice = join(create_session(context, live_server), "Alice")
    expect(alice.locator("#editor-status")).to_have_text("You're driving.")
    expect(alice.locator("#test-button")).to_have_count(0)


def driving_alice(context, live_server) -> Page:
    alice = join(create_session(context, live_server), "Alice")
    expect(alice.locator("#editor-status")).to_have_text("You're driving.")
    alice.locator(".CodeMirror").click()
    return alice


def test_ctrl_space_completes_with_jedi(live_server, context):
    alice = driving_alice(context, live_server)
    alice.keyboard.type("import collections\ncollections.Coun")
    alice.keyboard.press("Control+Space")

    expect(alice.locator(".CodeMirror-hints")).to_contain_text(
        "Counter", timeout=90_000
    )
    alice.keyboard.press("Enter")
    expect(alice.locator(".CodeMirror")).to_contain_text("collections.Counter")


def test_ruff_flags_problems_as_you_type(live_server, context):
    alice = driving_alice(context, live_server)
    alice.keyboard.type("import os\n")

    marker = alice.locator(".CodeMirror-lint-marker").first
    expect(marker).to_be_visible(timeout=60_000)
    marker.hover()
    expect(alice.locator(".CodeMirror-lint-tooltip")).to_contain_text("F401")


def test_format_button_formats_with_ruff(live_server, context):
    alice = driving_alice(context, live_server)
    alice.keyboard.type("x=[1,2]")
    alice.click("#format-button")

    alice.wait_for_function("editor.getValue() === 'x = [1, 2]\\n'", timeout=60_000)
