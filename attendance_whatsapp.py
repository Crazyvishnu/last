#!/usr/bin/env python3
"""
Minimal attendance fetcher + Telegram notifier.

Config via environment (GitHub Actions Secrets & Variables):
- TELEGRAM_BOT_TOKEN (required)
- TELEGRAM_CHAT_ID (required)
- MGIT_COOKIE (optional)  => cookie string like "PHPSESSID=abc; other=val"
- ATTENDANCE_URL (optional, default uses theMGIT URL in your screenshot)
- TIMEOUT_SECONDS (optional, default 30)
"""

from __future__ import annotations
import os
import re
import requests
import datetime
import sys
from typing import Optional, Dict

# Defaults
DEFAULT_URL = "https://mgit.winnou.net/index.php?option=com_base_studentinfo&task=details&schoolid=1&Itemid=324"
ATT_REGEX_PARENTHESES = re.compile(r"Attendance\s*:.*\(\s*(\d{1,3}(?:\.\d+)?)\s*\)", re.IGNORECASE)
ATT_REGEX_PERCENT = re.compile(r"(\d{1,3}(?:\.\d+)?%)")
ATT_GENERIC_NUMBER = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*(?:%|$)")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
MGIT_COOKIE = os.environ.get("MGIT_COOKIE")  # optional
ATTENDANCE_URL = os.environ.get("ATTENDANCE_URL", DEFAULT_URL)
TIMEOUT_SECONDS = int(os.environ.get("TIMEOUT_SECONDS", "30"))

HEADERS = {"User-Agent": "attendance-notifier/1.0 (+https://github.com/your/repo)"}


def fetch_page_text(url: str, timeout: int = 30, cookie: Optional[str] = None) -> Dict[str, object]:
    cookies = {}
    if cookie:
        parts = [p.strip() for p in cookie.split(";") if p.strip()]
        for p in parts:
            if "=" in p:
                k, v = p.split("=", 1)
                cookies[k.strip()] = v.strip()
    try:
        resp = requests.get(url, headers=HEADERS, cookies=cookies or None, timeout=timeout)
        return {"ok": resp.ok, "status_code": resp.status_code, "text": resp.text, "error": None if resp.ok else f"HTTP {resp.status_code}"}
    except Exception as exc:
        return {"ok": False, "status_code": 0, "text": "", "error": str(exc)}


def extract_attendance(html: str) -> Optional[str]:
    # 1) Look for "Attendance : ... (75.95)" style (matches your screenshot)
    m = ATT_REGEX_PARENTHESES.search(html)
    if m:
        return f"{m.group(1)}%"
    # 2) Look for percent token anywhere
    m = ATT_REGEX_PERCENT.search(html)
    if m:
        return m.group(1)
    # 3) Fallback: find first reasonably sized number (0-100)
    m = ATT_GENERIC_NUMBER.search(html)
    if m:
        # if already has % nearby or we want to append percent
        val = m.group(1)
        # If it's > 0 and <=100, return with percent
        try:
            num = float(val)
            if 0 <= num <= 100:
                return f"{val}%"
        except Exception:
            pass
    return None


def send_telegram_message(bot_token: str, chat_id: str, text: str, timeout: int = 20) -> bool:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return True


def build_message(att: str, status: str, details: Optional[Dict] = None) -> str:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    details_text = f"\n\n<code>{details}</code>" if details else ""
    return (
        f"📊 <b>MGIT Attendance Update</b>\n\n"
        f"Your current attendance: <b>{att}</b>\n\n"
        f"Checked at: <code>{now}</code>\nStatus: <b>{status}</b>{details_text}"
    )


def main() -> int:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERROR: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in environment", file=sys.stderr)
        return 2

    page = fetch_page_text(ATTENDANCE_URL, timeout=TIMEOUT_SECONDS, cookie=MGIT_COOKIE)
    if not page["ok"]:
        attendance = "Attendance not found"
        status = "fetch_failed"
        details = {"error": page["error"], "status": page["status_code"]}
    else:
        attendance_val = extract_attendance(page["text"])
        if attendance_val:
            attendance = attendance_val
            status = "ok"
            details = {"status_code": page["status_code"]}
        else:
            attendance = "Attendance not found"
            status = "not_found"
            details = {"status_code": page["status_code"]}

    message = build_message(attendance, status, details)

    try:
        send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, message)
        print("Message sent:", attendance)
        return 0
    except Exception as exc:
        print("Failed to send Telegram message:", exc, file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
