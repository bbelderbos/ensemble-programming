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
    expect(alice.locator("#code-panel .CodeMirror")).to_contain_text("def sum_numbers")

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


def test_joining_before_the_connection_opens_still_registers(live_server, context):
    page = context.new_page()
    # Real networks take a while to open WebSockets; joining must not race them
    cdp = context.new_cdp_session(page)
    cdp.send(
        "Network.emulateNetworkConditions",
        {
            "offline": False,
            "latency": 800,
            "downloadThroughput": -1,
            "uploadThroughput": -1,
        },
    )
    page.goto(live_server)
    page.fill("input[name=goal]", "x")
    page.click("text=Create Session")
    page.wait_for_url(re.compile("/session/"))
    join(page, "Alice")

    expect(page.locator("#participant-list")).to_contain_text("Alice", timeout=10_000)


def test_cmd_enter_runs_the_code(live_server, context):
    alice = driving_alice(context, live_server)
    alice.keyboard.type('print("shortcut")')
    alice.keyboard.press("ControlOrMeta+Enter")

    expect(alice.locator("#stdout")).to_have_text("shortcut", timeout=90_000)


def test_non_drivers_see_why_they_cannot_type(live_server, context):
    alice = join(create_session(context, live_server), "Alice")
    bob = open_and_join(context, alice.url, "Bob")

    expect(bob.locator("#readonly-banner")).to_be_visible()
    expect(bob.locator("#readonly-banner")).to_contain_text("Alice is driving")
    expect(alice.locator("#readonly-banner")).to_be_hidden()


def test_copy_invite_link(live_server, context):
    context.grant_permissions(["clipboard-read", "clipboard-write"])
    alice = join(create_session(context, live_server), "Alice")
    alice.click("#copy-link")

    expect(alice.locator("#copy-link")).to_contain_text("Copied")
    assert alice.evaluate("navigator.clipboard.readText()") == alice.url


def test_session_shows_its_goal(live_server, context):
    alice = join(create_session(context, live_server), "Alice")

    expect(alice.locator("#session-goal")).to_have_text("FizzBuzz")


def test_challenge_tests_live_in_a_highlighted_tab(live_server, context):
    alice = context.new_page()
    alice.goto(live_server)
    alice.get_by_role("button", name="Sum n numbers").click()
    alice.wait_for_url(re.compile("/session/"))
    join(alice, "Alice")

    expect(alice.locator("#tests-panel")).to_be_hidden()
    alice.click("#tests-tab")
    tests_panel = alice.locator("#tests-panel")
    expect(tests_panel).to_contain_text("def test_sum_numbers_default_args")
    expect(tests_panel.locator(".cm-keyword").first).to_be_visible()


def test_timekeeper_can_rotate_now(live_server, context):
    alice = join(create_session(context, live_server), "Alice")
    bob = open_and_join(context, alice.url, "Bob")

    expect(alice.locator("#rotate-button")).to_be_hidden()
    bob.click("#rotate-button")
    expect(bob.locator("#editor-status")).to_have_text("You're driving.")


def test_save_shortcut_formats(live_server, context):
    alice = driving_alice(context, live_server)
    alice.keyboard.type("x=1")
    alice.keyboard.press("ControlOrMeta+s")

    alice.wait_for_function("editor.getValue() === 'x = 1\\n'", timeout=60_000)


def test_names_are_shown_as_text_not_html(live_server, context):
    alice = join(create_session(context, live_server), "<b>Al</b>")

    expect(alice.locator("#participant-list")).to_contain_text("<b>Al</b>")
    expect(alice.locator("#participant-list b")).to_have_count(0)
