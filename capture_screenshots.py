"""
Capture real screenshots of the CaseLens Streamlit app with Playwright.

Runs the app as a subprocess (live API calls — set ANTHROPIC_API_KEY) and
captures the research view, a cited answer, the Cross-Reference Map, and the
Defined-Terms glossary.

Usage: python capture_screenshots.py
"""

import os
import sys
import subprocess
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

PORT = 8503
BASE_URL = f"http://localhost:{PORT}"
CHROMIUM_EXEC = os.getenv("CHROMIUM_EXEC", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
SHOTS = Path("screenshots")
SHOTS.mkdir(exist_ok=True)


def wait_for_app(timeout: int = 90) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if requests.get(BASE_URL, timeout=2).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def wait_idle(page, timeout_ms: int = 60000) -> None:
    try:
        page.wait_for_selector("[data-testid='stStatusWidget']", timeout=4000)
        page.wait_for_selector("[data-testid='stStatusWidget']", state="detached", timeout=timeout_ms)
    except PWTimeout:
        pass
    page.wait_for_timeout(1500)


def click_tab(page, label: str) -> None:
    page.locator("button[role='tab']", has_text=label).first.click()
    page.wait_for_timeout(1200)


def main():
    env = os.environ.copy()
    if not env.get("ANTHROPIC_API_KEY"):
        sys.exit("Error: ANTHROPIC_API_KEY not set. Add it to .env or export it.")
    env.setdefault("LAW_ANTHROPIC_BASE_URL", "https://api.anthropic.com")

    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py",
         "--server.port", str(PORT), "--server.headless", "true",
         "--server.fileWatcherType", "none", "--browser.gatherUsageStats", "false"],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        print(f"Waiting for Streamlit on :{PORT} …")
        if not wait_for_app():
            proc.kill()
            print("STDERR:", proc.communicate()[1].decode()[-2000:])
            sys.exit("Streamlit did not start.")
        time.sleep(2)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=CHROMIUM_EXEC)
            page = browser.new_context(viewport={"width": 1340, "height": 1000}).new_page()

            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_timeout(3500)
            page.screenshot(path=str(SHOTS / "01_research_view.png"), full_page=True)
            print("  01_research_view.png")

            # Ask the first example question.
            page.locator("button", has_text="What is each party's cap on liability").first.click()
            wait_idle(page)
            page.screenshot(path=str(SHOTS / "02_cited_answer.png"), full_page=True)
            print("  02_cited_answer.png")

            # Expand the authorities and reasoning-path expanders.
            for label in ["Authorities", "Reasoning path"]:
                exp = page.locator("summary", has_text=label).last
                try:
                    exp.scroll_into_view_if_needed()
                    exp.click()
                    page.wait_for_timeout(700)
                except Exception:
                    pass
            page.screenshot(path=str(SHOTS / "03_authorities_and_path.png"), full_page=True)
            print("  03_authorities_and_path.png")

            click_tab(page, "Cross-Reference Map")
            page.screenshot(path=str(SHOTS / "04_cross_reference_map.png"), full_page=True)
            print("  04_cross_reference_map.png")

            click_tab(page, "Defined Terms")
            page.screenshot(path=str(SHOTS / "05_defined_terms.png"), full_page=True)
            print("  05_defined_terms.png")

            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    print("\nScreenshot sizes:")
    ok = True
    for png in sorted(SHOTS.glob("*.png")):
        size = png.stat().st_size
        print(f"  {png.name}: {size:,} bytes")
        ok = ok and size > 10_000
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
