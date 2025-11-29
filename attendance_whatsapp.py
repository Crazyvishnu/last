#!/usr/bin/env python3
"""
attendance_whatsapp.py

MGIT Attendance WhatsApp Bot (Twilio) - Robust version with diagnostics and optional Selenium fallback.

Usage:
  - configure environment variables (see README section below)
  - run: python attendance_whatsapp.py
"""

import os
import re
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from twilio.rest import Client

# Optional selenium import (only used when USE_SELENIUM=1)
USE_SELENIUM = os.environ.get("USE_SELENIUM", "0") in ("1", "true", "True", "yes", "y")
if USE_SELENIUM:
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
    except Exception as e:
        print("⚠️ Selenium requested but selenium package not available:", e)
        USE_SELENIUM = False

# -------------------------
# Environment / Config
# -------------------------
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
TWILIO_WHATSAPP_FROM = os.environ.get('TWILIO_WHATSAPP_FROM')  # e.g. whatsapp:+14155238886
YOUR_WHATSAPP_NUMBER = os.environ.get('YOUR_WHATSAPP_NUMBER')  # e.g. whatsapp:+919876543210
MGIT_USERNAME = os.environ.get('MGIT_USERNAME')
MGIT_PASSWORD = os.environ.get('MGIT_PASSWORD')

# Optional developer number to receive debug/failures (set to None to skip)
DEV_WHATSAPP_NUMBER = os.environ.get('DEV_WHATSAPP_NUMBER')  # e.g. whatsapp:+91xxxxxxxxxx

BASE_URL = os.environ.get('BASE_URL', "https://mgit.winnou.net").rstrip('/')

# Timeouts and limits
HTTP_TIMEOUT = int(os.environ.get('HTTP_TIMEOUT', '20'))
HTML_PREVIEW_CHARS = int(os.environ.get('HTML_PREVIEW_CHARS', '800'))

# -------------------------
# Helper: send WhatsApp via Twilio
# -------------------------
def send_whatsapp_message(message, to_number=None):
    """Send message via Twilio WhatsApp. Returns True on success."""
    if to_number is None:
        to_number = YOUR_WHATSAPP_NUMBER

    try:
        if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM, to_number]):
            print("❌ Missing Twilio / destination configuration!")
            print(f"   SID: {'✓' if TWILIO_ACCOUNT_SID else '✗'}")
            print(f"   Token: {'✓' if TWILIO_AUTH_TOKEN else '✗'}")
            print(f"   From: {'✓' if TWILIO_WHATSAPP_FROM else '✗'}")
            print(f"   To: {'✓' if to_number else '✗'}")
            return False

        print(f"📱 Twilio SID: {TWILIO_ACCOUNT_SID[:10]}...")
        print(f"📤 From: {TWILIO_WHATSAPP_FROM}")
        print(f"📥 To: {to_number}")

        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        msg = client.messages.create(from_=TWILIO_WHATSAPP_FROM, body=message, to=to_number)
        print("✅ WhatsApp sent successfully!")
        print(f"   Message SID: {msg.sid}")
        print(f"   Status: {msg.status}")
        return True

    except Exception as e:
        print(f"❌ Twilio Error: {e}")
        return False

# -------------------------
# Optional Selenium fallback function
# -------------------------
def fetch_with_selenium(path="/student/attendance", login_path="/login"):
    """Return page HTML for attendance using Selenium (headless).
    Requires chromedriver & selenium package. Returns HTML string or raises Exception.
    """
    if not USE_SELENIUM:
        raise RuntimeError("Selenium not enabled (USE_SELENIUM env var).")

    username_field_names = ["username", "user", "rollno", "email", "userid", "studentid"]
    password_field_names = ["password", "passwd", "pwd"]

    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    # opts.add_argument("--disable-gpu")
    driver = webdriver.Chrome(options=opts)
    try:
        login_url = BASE_URL + login_path if not login_path.startswith('http') else login_path
        print("🔁 Selenium -> opening login page:", login_url)
        driver.get(login_url)
        time.sleep(2)

        # try to find username & password fields by common names or input[type=password]
        username_input = None
        password_input = None

        for name in username_field_names:
            try:
                username_input = driver.find_element(By.NAME, name)
                break
            except:
                pass

        try:
            password_input = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
        except:
            # fallback common names
            for name in password_field_names:
                try:
                    password_input = driver.find_element(By.NAME, name)
                    break
                except:
                    pass

        if username_input is None or password_input is None:
            raise RuntimeError("Could not locate username/password inputs with Selenium. Inspect selectors.")

        username_input.clear()
        username_input.send_keys(MGIT_USERNAME)
        password_input.clear()
        password_input.send_keys(MGIT_PASSWORD)

        # try submit: click a button[type=submit] or press ENTER
        try:
            submit_btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            submit_btn.click()
        except:
            password_input.send_keys("\n")
        time.sleep(3)

        # navigate to attendance page
        target = BASE_URL + path if not path.startswith('http') else path
        print("🔁 Selenium -> navigating to attendance page:", target)
        driver.get(target)
        time.sleep(2)
        return driver.page_source

    finally:
        try:
            driver.quit()
        except:
            pass

# -------------------------
# Main: fetch attendance with requests (robust)
# -------------------------
def get_attendance():
    """Fetch attendance from MGIT portal — robust with diagnostics and parsing methods.
    Returns a formatted message string on success, or an error string beginning with an emoji.
    """
    # If user explicitly opts for selenium fallback, use that
    if USE_SELENIUM:
        try:
            html = fetch_with_selenium(path="/student/attendance", login_path="/login")
            # reuse parsing on returned html later
            return parse_attendance_html(html)
        except Exception as e:
            err = f"❌ Selenium fetch failed: {e}"
            print(err)
            # continue to try requests approach as fallback

    try:
        session = requests.Session()
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        print("📡 Accessing MGIT portal base:", BASE_URL)
        r0 = session.get(BASE_URL, headers=headers, timeout=HTTP_TIMEOUT, allow_redirects=True)
        print(f"Initial GET -> status: {r0.status_code}, url: {r0.url}")
        print("Preview:", r0.text[:HTML_PREVIEW_CHARS].replace("\n", " ")[:HTML_PREVIEW_CHARS])

        if r0.status_code != 200:
            return f"❌ Cannot reach MGIT portal (Status: {r0.status_code}, URL: {r0.url})"

        # parse initial page to find a login form (and hidden fields)
        soup = BeautifulSoup(r0.text, "html.parser")
        form = soup.find("form")
        hidden_fields = {}
        form_action = None
        if form:
            form_action = form.get("action")
            for inp in form.find_all("input", {"type": "hidden"}):
                name = inp.get("name")
                value = inp.get("value", "")
                if name:
                    hidden_fields[name] = value

        # Build login payload with common field names plus hidden tokens
        login_payload = {
            'username': MGIT_USERNAME,
            'password': MGIT_PASSWORD,
            'user': MGIT_USERNAME,
            'userid': MGIT_USERNAME,
            'rollno': MGIT_USERNAME,
            'passwd': MGIT_PASSWORD,
            'pwd': MGIT_PASSWORD,
            **hidden_fields
        }

        # Determine login URL
        if form_action:
            login_url = form_action if form_action.startswith("http") else (BASE_URL + form_action if form_action.startswith("/") else BASE_URL + "/" + form_action)
        else:
            # try common login endpoints
            candidates = ["/login", "/accounts/login", "/auth/login", "/users/login"]
            login_url = None
            for c in candidates:
                test_url = BASE_URL + c
                try:
                    head = session.head(test_url, headers=headers, timeout=6, allow_redirects=True)
                    if head.status_code in (200, 302):
                        login_url = test_url
                        break
                except Exception:
                    continue
            if not login_url:
                login_url = BASE_URL + "/login"

        print("🔐 Logging in as:", MGIT_USERNAME)
        headers['Referer'] = r0.url
        login_resp = session.post(login_url, data=login_payload, headers=headers, timeout=HTTP_TIMEOUT, allow_redirects=True)
        print(f"Login POST -> status: {login_resp.status_code}, url: {login_resp.url}")
        print("Login response preview:", login_resp.text[:HTML_PREVIEW_CHARS].replace("\n", " ")[:HTML_PREVIEW_CHARS])

        # quick login checks
        if login_resp.status_code >= 400:
            return f"❌ Login POST failed (Status: {login_resp.status_code})"
        if any(k in login_resp.text.lower() for k in ("invalid", "incorrect", "unauthorized", "login failed", "error")):
            return "❌ Login failed! Check your MGIT username and password."

        # search for attendance link in the logged-in page
        soup = BeautifulSoup(login_resp.text, "html.parser")
        attendance_href = None
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            text = a.get_text(" ", strip=True).lower()
            if "attendance" in href.lower() or "attendance" in text:
                attendance_href = href
                break

        # check data-* attributes and scripts
        if not attendance_href:
            for elem in soup.find_all(True):
                for attr in ("data-href", "data-url", "data-target", "onclick"):
                    val = elem.get(attr)
                    if val and "attendance" in val.lower():
                        attendance_href = val
                        break
                if attendance_href:
                    break

        if not attendance_href:
            # fallback default path you used earlier
            attendance_href = "/student/attendance"

        # normalize attendance URL
        attendance_url = attendance_href if attendance_href.startswith("http") else BASE_URL + (attendance_href if attendance_href.startswith("/") else "/" + attendance_href)
        print("📊 Fetching attendance:", attendance_url)

        att_resp = session.get(attendance_url, headers=headers, timeout=HTTP_TIMEOUT, allow_redirects=True)
        print(f"Attendance GET -> status: {att_resp.status_code}, url: {att_resp.url}")
        print("Attendance preview:", att_resp.text[:HTML_PREVIEW_CHARS].replace("\n", " ")[:HTML_PREVIEW_CHARS])

        if att_resp.status_code == 404:
            # search combined page for possible XHR endpoints
            combined = login_resp.text + att_resp.text
            endpoints = re.findall(r'(["\'])(\/[^\s"\']*attendance[^\s"\']*)\1', combined, re.I)
            if endpoints:
                candidates = [BASE_URL + ep[1] for ep in endpoints]
                return f"❌ Attendance page returned 404. Possible endpoints found: {', '.join(candidates[:5])}\nTry calling them with the same session (cookies)."
            return f"❌ Could not access attendance page (Status: 404)."

        if att_resp.status_code != 200:
            return f"❌ Could not access attendance page (Status: {att_resp.status_code}, URL: {att_resp.url})"

        # parse & format attendance message
        return parse_attendance_html(att_resp.text)

    except requests.exceptions.Timeout:
        return "⏱️ Request timed out. MGIT portal might be slow."
    except requests.exceptions.ConnectionError:
        return "🌐 Connection error. Please check connectivity."
    except Exception as e:
        print("Exception trace:", str(e))
        return f"❌ Error: {str(e)[:200]}\n\nPlease verify credentials."

# -------------------------
# Parser: produce final WhatsApp message from HTML
# -------------------------
def parse_attendance_html(html_text):
    """Parse HTML and return formatted attendance message or error string."""
    soup = BeautifulSoup(html_text, "html.parser")
    attendance_data = []

    # Method 1: find spans/divs/labels containing percentages
    for elem in soup.find_all(['span', 'label', 'div', 'td', 'th']):
        text = elem.get_text(" ", strip=True)
        if not text or len(text) > 400:
            continue
        # look for pattern like '74.6' or '74.6 %' or '(74.6)'
        pct_match = re.search(r'\(?\b(\d{1,3}\.?\d*)\b\)?\s*%?', text)
        if pct_match and '%' in text or re.search(r'\battendance\b', text, re.I) or ('%' in text and len(text.split()) <= 6):
            # try to find a subject name
            pct = float(pct_match.group(1))
            subj = None
            # check parent row or sibling
            parent = elem.find_parent()
            if parent:
                # look for strong/b elements
                s = parent.find(['strong', 'b'])
                if s and s.get_text(strip=True):
                    subj = s.get_text(strip=True)
                else:
                    # try previous sibling text
                    prev = elem.find_previous(string=True)
                    if prev and isinstance(prev, str):
                        prev_text = prev.strip()
                        if prev_text and not re.match(r'^\d', prev_text):
                            subj = prev_text[:50]
            attendance_data.append({'subject': subj or 'Subject', 'percentage': pct})

    # Method 2: table parsing as fallback
    if not attendance_data:
        for table in soup.find_all('table'):
            rows = table.find_all('tr')
            for row in rows[1:]:
                cols = [c.get_text(" ", strip=True) for c in row.find_all(['td', 'th'])]
                if len(cols) >= 2:
                    last = cols[-1]
                    m = re.search(r'(\d{1,3}\.?\d*)\s*%?', last)
                    if m:
                        try:
                            attendance_data.append({'subject': cols[0][:50], 'percentage': float(m.group(1))})
                        except:
                            continue

    # Method 3: raw regex on text
    if not attendance_data:
        text = soup.get_text(" ", strip=True)
        matches = re.findall(r'([A-Za-z0-9\-&\s]{4,80})[:\-\s]{1,4}(\d{1,3}\.?\d*)\s*%', text)
        for subj, pct in matches[:20]:
            attendance_data.append({'subject': subj.strip()[:50], 'percentage': float(pct)})

    if not attendance_data:
        return "⚠️ Could not extract attendance data. Page layout changed or site uses JS/XHR."

    # deduplicate and trim
    seen = set()
    unique = []
    for it in attendance_data:
        key = f"{it['subject']}-{it['percentage']}"
        if key not in seen:
            seen.add(key)
            unique.append(it)
    attendance_data = unique[:20]

    # build message
    message = "📚 *MGIT Attendance Report*\n"
    message += f"⏰ {datetime.now().strftime('%d-%b-%Y %I:%M %p')} IST\n"
    message += f"👤 {MGIT_USERNAME}\n"
    message += "━━━━━━━━━━━━━━━━━━\n\n"
    for item in attendance_data:
        pct = item['percentage']
        subj = item['subject']
        emoji = "✅" if pct >= 75 else ("⚠️" if pct >= 65 else "🔴")
        message += f"{emoji} *{subj}*: {pct}%\n"
    avg = sum(i['percentage'] for i in attendance_data) / len(attendance_data)
    message += f"\n━━━━━━━━━━━━━━━━━━\n📊 Average: {avg:.1f}%\n✅ ≥75% | ⚠️ 65-74% | 🔴 <65%"

    return message

# -------------------------
# Main entrypoint
# -------------------------
def main():
    print("\n" + "="*70)
    print("🎓 MGIT ATTENDANCE WHATSAPP BOT (TWILIO) - Robust")
    print("="*70)
    print(f"⏰ Execution: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} IST")
    print(f"👤 User: {MGIT_USERNAME}")
    print(f"📱 WhatsApp: {YOUR_WHATSAPP_NUMBER}")
    print(f"🔁 Selenium fallback enabled: {USE_SELENIUM}")
    print("="*70 + "\n")

    print("STEP 1: Fetching attendance from MGIT portal...")
    print("-"*70)
    attendance = get_attendance()
    print("-"*70)
    print("Fetch result (trimmed):")
    print(attendance[:1500])
    print("-"*70)

    # Decide whether to send
    error_prefixes = ("❌", "⚠️ Could not extract", "⏱️", "🌐", "⚠️ Could not access", "❌ Selenium fetch failed")
    if any(attendance.startswith(p) for p in error_prefixes):
        print("\nSTEP 2: Fetch failed — not sending attendance to student WhatsApp to avoid confusion.")
        print(f"Reason: {attendance}")
        # Optionally, send debug to developer/dev number
        if DEV_WHATSAPP_NUMBER:
            print("Sending debug message to DEV_WHATSAPP_NUMBER...")
            debug_msg = f"⚠️ Attendance fetch failed for {MGIT_USERNAME} at {datetime.now().strftime('%d-%b-%Y %I:%M %p')} IST\n\n{attendance}"
            send_whatsapp_message(debug_msg, to_number=DEV_WHATSAPP_NUMBER)
        else:
            print("DEV_WHATSAPP_NUMBER not set — skipping debug message.")
    else:
        print("\nSTEP 2: Sending to WhatsApp via Twilio...")
        print("-"*70)
        ok = send_whatsapp_message(attendance)
        if ok:
            print("\n✅ SUCCESS! Message sent to WhatsApp")
            print(f"   Check your WhatsApp: {YOUR_WHATSAPP_NUMBER}")
        else:
            print("\n⚠️ FAILED to send WhatsApp. See Twilio errors above.")

    print("\n" + "="*70)
    print("Run completed.")
    print("="*70 + "\n")

if __name__ == "__main__":
    main()

"""
README / quick checklist:

1) Environment variables (required):
   - TWILIO_ACCOUNT_SID
   - TWILIO_AUTH_TOKEN
   - TWILIO_WHATSAPP_FROM   (format: whatsapp:+14155238886)
   - YOUR_WHATSAPP_NUMBER   (format: whatsapp:+91xxxxxxxxxx)
   - MGIT_USERNAME
   - MGIT_PASSWORD

   Optional:
   - DEV_WHATSAPP_NUMBER (receive debug messages)
   - USE_SELENIUM=1 to enable selenium fallback (requires chromedriver & selenium)
   - BASE_URL if your portal base is different.

2) Python packages:
   pip install requests beautifulsoup4 lxml twilio
   Optional for selenium: pip install selenium
   Also install chromedriver matching your Chrome version and ensure it's in PATH.

3) If you get 404 or no attendance data:
   - Run the script locally and inspect printed "Login POST -> status/url" and "Attendance GET -> status/url" snippets.
   - Open browser DevTools -> Network while logged in and find the XHR endpoint for attendance.
   - If XHR exists, adapt the script to call that endpoint (same session cookies).

4) GitHub Actions:
   - Add secrets for TWILIO_* and MGIT_* credentials.
   - Use the cron schedule in your workflow as before.

5) Removing Twilio trial prefix:
   - Upgrade Twilio account from trial to paid (trial messages include the trial prefix).

"""

