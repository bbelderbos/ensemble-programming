import asyncio
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.async_api import Page, async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8765"
OUT = Path(tempfile.mkdtemp(prefix="demo-recording-"))
VIDEO = Path(__file__).parent / "demo.mp4"
SIZE = {"width": 720, "height": 840}

ALICE_CODE = """def fizzbuzz(n):
    if n % 15 == 0:
        return "FizzBuzz"
    if n % 3 == 0:
        return "Fizz"
    return str(n)

print(", ".join(fizzbuzz(i) for i in range(1, 16)))
"""

BOB_FIX = """    if n % 5 == 0:
        return "Buzz"
"""

OVERLAY_JS = """
([who, color]) => {
  const badge = document.createElement('div');
  badge.textContent = who + "'s browser";
  badge.style.cssText = `position:fixed;top:10px;right:10px;z-index:9999;padding:6px 14px;
    border-radius:999px;background:${color};color:#fff;font:600 15px system-ui`;
  document.body.appendChild(badge);
  const style = document.createElement('style');
  style.textContent = '#output { white-space: pre-wrap; word-break: break-word; }';
  document.head.appendChild(style);
}
"""


FLASH_JS = """
() => {
  const m = document.createElement('div');
  m.style.cssText = 'position:fixed;top:0;left:0;width:12px;height:12px;background:#f00;z-index:99999';
  document.body.appendChild(m);
  setTimeout(() => m.remove(), 400);
}
"""


async def overlay(page: Page, who: str, color: str) -> None:
    await page.evaluate(OVERLAY_JS, [who, color])


async def flash_sync_marker(pages: list[Page]) -> None:
    await asyncio.gather(*(p.evaluate(FLASH_JS) for p in pages))


def marker_time(video: Path) -> float:
    # First frame where the red corner marker shows (V chroma jumps from ~128 to ~240)
    stats = subprocess.run(
        [
            "ffmpeg",
            "-i",
            video,
            "-vf",
            "crop=8:8:0:0,signalstats,metadata=print:key=lavfi.signalstats.VAVG:file=-",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    for pts_line, value_line in zip(stats[::2], stats[1::2]):
        if float(value_line.split("=")[1]) > 200:
            return float(pts_line.split("pts_time:")[1])
    raise RuntimeError(f"sync marker not found in {video}")


ASS_HEADER = f"""[Script Info]
PlayResX: {SIZE["width"] * 2}
PlayResY: {SIZE["height"]}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, BackColour, BorderStyle, Outline, Shadow, Alignment, MarginV
Style: Default,Helvetica,26,&H00FFFFFF,&H1A27182B,3,12,0,2,28

[Events]
Format: Layer, Start, End, Style, Text
"""

captions: list[tuple[float, str]] = []
t0 = 0.0


async def caption(text: str) -> None:
    captions.append((time.monotonic() - t0, text))
    # Give viewers time to read each phase before the action starts
    await asyncio.sleep(1.5)


def ass_time(seconds: float) -> str:
    m, s = divmod(seconds, 60)
    return f"0:{int(m):02d}:{s:05.2f}"


def write_captions(path: Path, shift: float) -> None:
    ends = [start for start, _ in captions[1:]] + [time.monotonic() - t0]
    lines = [
        f"Dialogue: 0,{ass_time(start + shift)},{ass_time(stop + shift)},Default,{text}"
        for (start, text), stop in zip(captions, ends)
    ]
    path.write_text(ASS_HEADER + "\n".join(lines) + "\n")


def stitch(alice_video: Path, bob_video: Path) -> None:
    alice_mark, bob_mark = marker_time(alice_video), marker_time(bob_video)
    shift = min(alice_mark, bob_mark)
    subs = OUT / "captions.ass"
    write_captions(subs, shift)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            alice_video,
            "-i",
            bob_video,
            "-filter_complex",
            f"[0:v]trim=start={alice_mark - shift:.3f},setpts=PTS-STARTPTS[a];"
            f"[1:v]trim=start={bob_mark - shift:.3f},setpts=PTS-STARTPTS[b];"
            f"[a][b]hstack=inputs=2:shortest=1,subtitles={subs},fps=30,format=yuv420p[v]",
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-crf",
            "20",
            "-movflags",
            "+faststart",
            VIDEO,
        ],
        check=True,
    )


async def plain_enter(page: Page) -> None:
    # Skip CodeMirror auto-indent so typed indentation stays exact
    await page.evaluate(
        "editor.setOption('extraKeys', {Enter: cm => cm.replaceSelection('\\n')})"
    )


async def main() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        global t0
        ctx_a = await browser.new_context(
            viewport=SIZE, record_video_dir=OUT / "alice", record_video_size=SIZE
        )
        ctx_b = await browser.new_context(
            viewport=SIZE, record_video_dir=OUT / "bob", record_video_size=SIZE
        )
        alice, bob = await ctx_a.new_page(), await ctx_b.new_page()
        both = [alice, bob]

        await asyncio.gather(alice.goto(BASE), bob.goto(BASE))
        # Recordings start at slightly different moments; align them on this flash
        await flash_sync_marker(both)
        t0 = time.monotonic()
        await overlay(alice, "Alice", "#4f46e5")
        await overlay(bob, "Bob", "#059669")
        await caption("Alice starts a new ensemble session")
        await alice.wait_for_timeout(800)
        await alice.locator("input[name=goal]").press_sequentially(
            "Solve FizzBuzz together", delay=60
        )
        await alice.wait_for_timeout(600)
        await alice.get_by_role("button", name="Create Session").click()
        await alice.wait_for_url("**/session/**")
        await overlay(alice, "Alice", "#4f46e5")
        await caption("Alice joins; Bob waits for the session link")
        await alice.locator("#username-input").press_sequentially("Alice", delay=90)
        await alice.wait_for_timeout(400)
        await alice.get_by_role("button", name="Join").click()
        await alice.wait_for_timeout(1200)

        await bob.goto(alice.url)
        await overlay(bob, "Bob", "#059669")
        await caption("Bob opens the shared link and joins")
        await bob.locator("#username-input").press_sequentially("Bob", delay=90)
        await bob.wait_for_timeout(400)
        await bob.get_by_role("button", name="Join").click()
        await bob.wait_for_timeout(1500)
        await caption("Active users and the rotation timer stay in sync")
        await bob.wait_for_timeout(1500)

        for p in both:
            await plain_enter(p)

        await caption("Alice drives: every keystroke streams to Bob's editor")
        await alice.locator(".CodeMirror").click()
        await alice.keyboard.type(ALICE_CODE, delay=40)
        assert (
            await alice.evaluate("editor.getValue()") == ALICE_CODE
        ), "typing scrambled"
        await alice.wait_for_timeout(1500)

        await caption("Bob runs it: Python executes in his browser via Pyodide")
        await bob.evaluate("pyodideReady")  # already loading since page load
        await bob.get_by_role("button", name="Run Code").click()
        await bob.wait_for_timeout(3500)

        await caption("Missing Buzz! Bob takes the keyboard and adds it")
        await bob.evaluate("editor.focus(); editor.setCursor({line: 5, ch: 0})")
        await bob.keyboard.type(BOB_FIX, delay=40)
        await bob.wait_for_timeout(1500)
        final = await alice.evaluate("editor.getValue()")
        assert "Buzz" in final.split("Fizz")[1], final

        await caption("Alice sees the fix instantly and runs it")
        await alice.evaluate("pyodideReady")
        await alice.get_by_role("button", name="Run Code").click()
        await alice.wait_for_timeout(3500)
        await caption("Ensemble Programming: one codebase, one team")
        await alice.wait_for_timeout(3000)

        await ctx_a.close()
        await ctx_b.close()
        await browser.close()
        stitch(Path(await alice.video.path()), Path(await bob.video.path()))


asyncio.run(main())
