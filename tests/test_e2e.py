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
    expect(alice.locator("#output")).to_contain_text("hi 2", timeout=60_000)
