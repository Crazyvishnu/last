# === FILE: send_attendance_playwright.py ===
#!/usr/bin/env python3
"""
Playwright-based MGIT attendance scraper + Telegram notifier.

Config (from environment, set as GitHub Secrets & Actions Variables):
- TELEGRAM_BOT_TOKEN (secret)      - required
- TELEGRAM_CHAT_ID (secret)        - required
- MGIT_USERNAME (secret)           - required
- MGIT_PASSWORD (secret)           - required
- LOGIN_URL (variable)             - optional, default: https://mgit.winnou.net/index.php
- ATTENDANCE_URL (variable)        - optional, default: student info URL from screenshot
- TIMEOUT_SECONDS (variable)       - optional, default: 60
"""

from __future__ import annotations
import os
import re
import sys
import asyncio
import datetime
import json
from typing import Optional, Dict, List

import httpx
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

# --- Defaults & regexes
DEFAULT_LOGIN_URL = os.environ.get("LOGIN_URL", "https://mgit.winnou.net/index.php")
DEFAULT_ATTENDANCE_URL = os.environ.get(
    "ATTENDANCE_URL",
    "https://mgit.winnou.net/index.php?option=com_base_studentinfo&task=details&schoolid=1&Itemid=324",
)
TIMEOUT_SECONDS = int(os.environ.get("TIMEOUT_SECONDS", "60"))

# Regexes to extract attendance
ATT_REGEX_PARENTHESES = re.compile(r"Attendance\s*:.*\(\s*(\d{1,3}(?:\.\d+)?)\s*\)", re.IGNORECASE)
ATT_REGEX_PERCENT = re.compile(r"(\d{1,3}(?:\.\d+)?%)")
ATT_GENERIC_NUMBER = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*(?:%|$)")

# Env secrets (must be set)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
MGIT_USERNAME = os.environ.get("MGIT_USERNAME")
MGIT_PASSWORD = os.environ.get("MGIT_PASSWORD")

HEADERS = {"User-Agent": "attendance-playwright-notifier/1.0"}

# --- Helpers
def _ensure_envs() -> Optional[str]:
    missing = []
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "MGIT_USERNAME", "MGIT_PASSWORD"):
        if not globals().get(k):
            missing.append(k)
    if missing:
        return f"Missing required environment variables: {', '.join(missing)}"
    return None

async def _try_selectors_fill(page, selectors: List[str], value: str) -> bool:
    for sel in selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                await el.fill(value)
                return True
        except Exception:
            pass
    return False

async def _find_and_click_login(page) -> bool:
    # Try buttons by type/role/text
    candidates = [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Login")',
        'button:has-text("Sign in")',
        'button:has-text("Sign In")',
        'button:has-text("Log in")',
        'a:has-text("Login")',
    ]
    for sel in candidates:
        try:
            el = await page.query_selector(sel)
            if el:
                try:
                    await el.click()
                    return True
                except Exception:
                    try:
                        await page.evaluate("(el) => el.click()", el)
                        return True
                    except Exception:
                        pass
        except Exception:
            pass
    # Try submitting first form
    try:
        forms = await page.query_selector_all("form")
        if forms:
            try:
                await forms[0].evaluate("(f) => f.submit()")
                return True
            except Exception:
                pass
    except Exception:
        pass
    return False

def extract_attendance_from_html(html: str) -> Optional[str]:
    # 1) Parentheses pattern
    m = ATT_REGEX_PARENTHESES.search(html)
    if m:
        return f"{m.group(1)}%"
    # 2) Percent token anywhere
    m = ATT_REGEX_PERCENT.search(html)
    if m:
        return m.group(1)
    # 3) Generic number fallback (0-100)
    m = ATT_GENERIC_NUMBER.search(html)
    if m:
        try:
            num = float(m.group(1))
            if 0 <= num <= 100:
                return f"{m.group(1)}%"
        except Exception:
            pass
    return None

async def send_telegram_message(bot_token: str, chat_id: str, text: str) -> Dict:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()

# --- Core flow
async def run_flow() -> int:
    missing_err = _ensure_envs()
    if missing_err:
        print("ERROR:", missing_err, file=sys.stderr)
        return 2

    results: Dict[str, object] = {"attendance": None, "status": "not_started", "details": {}}

    # Launch Playwright and login
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            context = await browser.new_context(user_agent=HEADERS["User-Agent"])
            page = await context.new_page()

            # Navigate to login page
            try:
                await page.goto(DEFAULT_LOGIN_URL, timeout=TIMEOUT_SECONDS * 1000)
            except PWTimeout:
                results["status"] = "login_page_load_timeout"
                results["details"]["error"] = "Timeout loading login page"
                await browser.close()
                print("ERROR: Timeout loading login page", file=sys.stderr)
                return 3
            except Exception as exc:
                results["status"] = "login_page_error"
                results["details"]["error"] = str(exc)
                await browser.close()
                print("ERROR: Failed to load login page:", exc, file=sys.stderr)
                return 3

            # Try to detect login form fields and fill username/password
            # Common selectors for username and password
            username_selectors = [
                'input[name="username"]', 'input[name="user"]', 'input[name="login"]', 'input[id*="user"]',
                'input[placeholder*="User"]', 'input[placeholder*="Username"]', 'input[type="text"]'
            ]
            password_selectors = [
                'input[name="password"]', 'input[name="pass"]', 'input[id*="pass"]',
                'input[placeholder*="Password"]', 'input[type="password"]'
            ]

            filled_user = await _try_selectors_fill(page, username_selectors, MGIT_USERNAME)
            filled_pass = await _try_selectors_fill(page, password_selectors, MGIT_PASSWORD)

            # If the fields were not found by direct selectors, try heuristic: find input fields order
            if not (filled_user and filled_pass):
                try:
                    inputs = await page.query_selector_all("input")
                    # Heuristic: first visible text input and first password input
                    text_input = None
                    pass_input = None
                    for inp in inputs:
                        typ = (await inp.get_attribute("type")) or ""
                        name = (await inp.get_attribute("name")) or ""
                        if not text_input and typ and "text" in typ:
                            text_input = inp
                        if not pass_input and typ and "pass" in typ:
                            pass_input = inp
                    if not filled_user and text_input:
                        try:
                            await text_input.fill(MGIT_USERNAME)
                            filled_user = True
                        except Exception:
                            pass
                    if not filled_pass and pass_input:
                        try:
                            await pass_input.fill(MGIT_PASSWORD)
                            filled_pass = True
                        except Exception:
                            pass
                except Exception:
                    pass

            # If still not filled, try specific MGIT login form fields (fallback)
            if not (filled_user and filled_pass):
                # Try to fill generic inputs in order: first text-like then password-like
                try:
                    all_inputs = await page.query_selector_all("input")
                    text_idx = None
                    pass_idx = None
                    for i, inp in enumerate(all_inputs):
                        t = (await inp.get_attribute("type")) or ""
                        if text_idx is None and ("text" in t or t == "" or t == "email"):
                            text_idx = i
                        if pass_idx is None and "pass" in t:
                            pass_idx = i
                    if not filled_user and text_idx is not None:
                        await all_inputs[text_idx].fill(MGIT_USERNAME)
                        filled_user = True
                    if not filled_pass and pass_idx is not None:
                        await all_inputs[pass_idx].fill(MGIT_PASSWORD)
                        filled_pass = True
                except Exception:
                    pass

            # If not found inputs at all, continue — maybe site requires click to reveal login modal
            # Attempt clicking common login link
            if not (filled_user and filled_pass):
                try:
                    login_links = await page.query_selector_all('a:has-text("Login"), a:has-text("Sign in"), button:has-text("Login")')
                    if login_links:
                        await login_links[0].click()
                        await page.wait_for_timeout(1000)
                        # try fill again
                        filled_user = filled_user or await _try_selectors_fill(page, username_selectors, MGIT_USERNAME)
                        filled_pass = filled_pass or await _try_selectors_fill(page, password_selectors, MGIT_PASSWORD)
                except Exception:
                    pass

            # If fields filled, try to submit
            submit_ok = False
            if filled_user and filled_pass:
                submit_ok = await _find_and_click_login(page)
            else:
                # Try pressing Enter in the password field if available
                try:
                    pass_el = await page.query_selector('input[type="password"]')
                    if pass_el:
                        await pass_el.press("Enter")
                        submit_ok = True
                except Exception:
                    pass

            # Wait for navigation or an element indicating logged-in state
            try:
                # Wait until either URL changes or a common logged-in indicator appears
                await page.wait_for_timeout(2000)  # short wait after submit
                # Wait for either redirect or presence of "Student Info" text
                try:
                    await page.wait_for_selector("text=Student Info, text=Welcome", timeout=TIMEOUT_SECONDS * 1000)
                except Exception:
                    # Not strictly required — continue to navigate to ATTENDANCE_URL
                    pass
            except PWTimeout:
                pass

            # Navigate to attendance page (explicitly)
            try:
                await page.goto(DEFAULT_ATTENDANCE_URL, timeout=TIMEOUT_SECONDS * 1000)
            except PWTimeout:
                results["status"] = "attendance_page_load_timeout"
                results["details"]["error"] = "Timeout loading attendance page"
                await browser.close()
                print("ERROR: Timeout loading attendance page", file=sys.stderr)
                return 4
            except Exception as exc:
                results["status"] = "attendance_page_error"
                results["details"]["error"] = str(exc)
                await browser.close()
                print("ERROR: Failed to load attendance page:", exc, file=sys.stderr)
                return 4

            # Wait for content to render
            await page.wait_for_timeout(1000)

            # Try to get HTML content and extract attendance
            try:
                html = await page.content()
                attendance = extract_attendance_from_html(html)
                results["attendance"] = attendance
                if attendance:
                    results["status"] = "ok"
                    results["details"]["status_code"] = 200
                else:
                    results["status"] = "attendance_not_found"
                    results["details"]["status_code"] = 200
                # Close browser
                await browser.close()
            except Exception as exc:
                results["status"] = "extract_error"
                results["details"]["error"] = str(exc)
                await browser.close()
                print("ERROR extracting attendance:", exc, file=sys.stderr)
                return 5

    except Exception as exc:
        print("ERROR: Playwright failure:", exc, file=sys.stderr)
        return 6

    # Build and send Telegram message
    att_text = results.get("attendance") or "Attendance not found"
    status = results.get("status", "unknown")
    details = results.get("details", {})
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    diag = json.dumps(details, ensure_ascii=False)
    message = (
        f"📊 <b>MGIT Attendance Update</b>\n\n"
        f"Your current attendance: <b>{att_text}</b>\n\n"
        f"Checked at: <code>{now}</code>\nStatus: <b>{status}</b>\n\n<code>{diag}</code>"
    )

    try:
        await send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, message)
        print("OK: Message sent. Attendance:", att_text)
        return 0
    except Exception as exc:
        print("ERROR: Failed to send Telegram message:", exc, file=sys.stderr)
        return 7

# Entrypoint
if __name__ == "__main__":
    code = asyncio.run(run_flow())
    raise SystemExit(code)
