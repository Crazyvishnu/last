#!/usr/bin/env python3
"""
attendance_whatsapp.py

MGIT Attendance WhatsApp Bot (Twilio) - Full script with auto-detect login form and diagnostics.

Environment variables required:
 - TWILIO_ACCOUNT_SID
 - TWILIO_AUTH_TOKEN
 - TWILIO_WHATSAPP_FROM  (format: whatsapp:+14155238886)
 - YOUR_WHATSAPP_NUMBER  (format: whatsapp:+91XXXXXXXXXX)
 - MGIT_USERNAME
 - MGIT_PASSWORD

Optional:
 - DEV_WHATSAPP_NUMBER (to receive debug/failure messages)
 - USE_SELENIUM=1 to enable Selenium fallback (requires chromedriver & selenium)
 - BASE_URL to override default portal base URL
"""

import os
import re
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from twilio.rest import Client

# Optional selenium import (only used when USE_SELENIUM=1)
USE_SELENIUM = os.environ.get("USE_SELENIUM", "0").lower() in ("1", "true", "yes", "y")
if USE_SELENIUM:
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
    except Exception as e:
        print("⚠️ Selenium requested but selenium not available:", e)
        USE_SELENIUM = False

# -------------------------
# Environment / Config
# -------------------------
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
TWILIO_WHATSAPP_FROM = os.environ.get('TWILIO_WHATSAPP_FROM')  # e.g. whatsapp:+14155238886
YOUR_WHATSAPP_NUMBER = os.environ.get('YOUR_WHATSAPP_NUMBER')  # e.g. whatsapp:+919876543210
DEV_WHATSAPP_NUMBER = os.environ.get('DEV_WHATSAPP_NUMBER')    # optional developer debug number

MGIT_USERNAME = os.environ.get('MGIT_USERNAME')
MGIT_PASSWORD = os.environ.get('MGIT_PASSWORD')

BASE_URL = os.environ.get('BASE_URL', "https://mgit.winnou.net").rstrip('/')

HTTP_TIMEOUT = int(os.environ.get('HTTP_TIMEOUT', '20'))
HTML_PREVIEW_CHARS = int(os.environ.get('HTML_PREVIEW_CHARS', '800'))

# -------------------------
# Twilio WhatsApp helper
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
# Selenium fallback (optional)
# -------------------------
def fetch_with_selenium(path="/student/attendance", login_path="/login"):
    """Return page HTML for attendance using Selenium (headless)."""
    if not USE_SELENIUM:
        raise RuntimeError("Selenium not enabled (USE_SELENIUM env var).")

    username_field_names = ["username", "user", "rollno", "email", "userid", "studentid"]
    password_field_names = ["password", "passwd", "pwd"]

    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=opts)
    try:
        login_url = BASE_URL + login_path if not login_path.startswith('http') else login_path
        print("🔁 Selenium -> opening login page:", login_url)
        driver.get(login_url)
        time.sleep(2)

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

        try:
            submit_btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            submit_btn.click()
        except:
            password_input.send_keys("\n")
        time.sleep(3)

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
# Parse attendance HTML -> message
# -------------------------
def parse_attendance_html(html_text):
    """Parse HTML and return formatted attendance message or error string."""
    soup = BeautifulSoup(html_text, "html.parser")
    attendance_data = []

    # Method 1: look for elements containing % with short context
    for elem in soup.find_all(['span', 'label', 'div', 'td', 'th', 'li']):
        try:
            text = elem.get_text(" ", strip=True)
        except:
            continue
        if not text or len(text) > 400:
            continue
        pct_match = re.search(r'\(?\b(\d{1,3}\.?\d*)\b\)?\s*%?', text)
        if not pct_match:
            continue
        # heuristic: only accept if '%' present or 'attendance' word nearby or short fragment
        if '%' in text or re.search(r'\battendance\b', text, re.I) or (len(text.split()) <= 6 and re.search(r'\d', text)):
            try:
                pct = float(pct_match.group(1))
            except:
                continue
            subj = None
            parent = elem.find_parent()
            if parent:
                s = parent.find(['strong', 'b'])
                if s and s.get_text(strip=True):
                    subj = s.get_text(strip=True)
                else:
                    prev = elem.find_previous(string=True)
                    if prev and isinstance(prev, str):
                        prev_text = prev.strip()
                        if prev_text and not re.match(r'^\d', prev_text):
                            subj = prev_text[:50]
            attendance_data.append({'subject': subj or 'Subject', 'percentage': pct})

    # Method 2: table parsing fallback
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

    # Method 3: raw regex on page text
    if not attendance_data:
        text = soup.get_text(" ", strip=True)
        matches = re.findall(r'([A-Za-z0-9\-&\s]{4,80})[:\-\s]{1,4}(\d{1,3}\.?\d*)\s*%', text)
        for subj, pct in matches[:20]:
            attendance_data.append({'subject': subj.strip()[:50], 'percentage': float(pct)})

    if not attendance_data:
        return "⚠️ Could not extract attendance data. Page layout changed or site uses JS/XHR."

    # deduplicate & trim
    seen = set()
    unique = []
    for it in attendance_data:
        key = f"{it['subject']}-{it['percentage']}"
        if key not in seen:
            seen.add(key)
            unique.append(it)
    attendance_data = unique[:20]

    # build WhatsApp message
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
# Main fetch logic (requests) including auto-detect login submit
# -------------------------
def get_attendance():
    """Fetch attendance from MGIT portal. Returns message string or error string starting with emoji."""
    # Selenium fallback if enabled
    if USE_SELENIUM:
        try:
            html = fetch_with_selenium(path="/student/attendance", login_path="/index.php")
            return parse_attendance_html(html)
        except Exception as e:
            print("❗ Selenium fallback failed:", e)
            # continue to try requests approach

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

        # find login form (auto-detect)
        soup = BeautifulSoup(r0.text, "html.parser")
        form = soup.find("form")
        if not form:
            # try common Joomla/onEdu login form ids/classes
            form = soup.find('form', attrs={'id': 'login-form'}) or soup.find('form', attrs={'id': 'mod-login-form'}) or soup.find('form', attrs={'class':'signin'})

        if not form:
            print("⚠️ Could not find a login form in the initial HTML (will try common endpoints).")
        else:
            print("🔎 Login form found. Inspecting inputs...")

        # Determine login action URL
        form_action = form.get("action") if form else None
        if form_action:
            login_url = form_action if form_action.startswith("http") else (BASE_URL + form_action if form_action.startswith("/") else BASE_URL + "/" + form_action)
        else:
            # fallback common endpoints
            candidates = ["/index.php", "/login", "/accounts/login", "/auth/login"]
            login_url = None
            for c in candidates:
                test = BASE_URL + c
                try:
                    head = session.head(test, headers=headers, timeout=6, allow_redirects=True)
                    if head.status_code in (200, 302):
                        login_url = test
                        break
                except:
                    continue
            if not login_url:
                login_url = BASE_URL + "/index.php"

        # Build login payload by iterating inputs (auto-map username/password)
        login_payload = {}
        if form:
            for inp in form.find_all('input'):
                name = inp.get('name')
                if not name:
                    continue
                typ = (inp.get('type') or 'text').lower()
                value = inp.get('value', '')
                if typ == 'password':
                    login_payload[name] = MGIT_PASSWORD or value
                elif typ in ('text', 'email'):
                    lname = name.lower()
                    if any(k in lname for k in ('user', 'roll', 'id', 'uname', 'email')):
                        login_payload[name] = MGIT_USERNAME or value
                    elif value:
                        login_payload[name] = value
                    else:
                        # cautious: assume first text is username if nothing else
                        if 'username' not in login_payload.values():
                            login_payload[name] = MGIT_USERNAME
                        else:
                            login_payload[name] = value
                elif typ == 'hidden':
                    login_payload[name] = value
                elif typ == 'submit':
                    if value:
                        login_payload[name] = value
                else:
                    if value:
                        login_payload[name] = value

        # If site had no form or fields could not be detected, add common fields
        if not any(k for k in login_payload.keys() if any(x in k.lower() for x in ('user','roll','id','name','uname'))):
            login_payload.update({'username': MGIT_USERNAME, 'password': MGIT_PASSWORD})

        # Add Referer header
        headers['Referer'] = r0.url

        # Masked preview for logging
        masked_payload = {k: ('***' if 'pass' in k.lower() else (v if len(str(v)) < 80 else str(v)[:60] + '...')) for k,v in login_payload.items()}
        print("➡️ POSTing login to:", login_url)
        print("➡️ Payload keys:", list(login_payload.keys()))
        print("➡️ Payload preview (masked):", masked_payload)

        login_resp = session.post(login_url, data=login_payload, headers=headers, timeout=HTTP_TIMEOUT, allow_redirects=True)
        print(f"Login POST -> status: {login_resp.status_code}, url: {login_resp.url}")
        print("Login response preview:", login_resp.text[:HTML_PREVIEW_CHARS].replace("\n", " ")[:HTML_PREVIEW_CHARS])

        if login_resp.status_code >= 400:
            return f"❌ Login POST failed (Status: {login_resp.status_code})"
        if any(k in login_resp.text.lower() for k in ("invalid", "incorrect", "unauthorized", "login failed", "please login", "sign in", "captcha")):
            return "❌ Login failed! Check your MGIT username and password, or the site may require captcha/JS."

        # Attempt to discover attendance URL in logged-in HTML
        soup = BeautifulSoup(login_resp.text, "html.parser")
        attendance_href = None
        for a in soup.find_all(["a", "button"], href=True):
            href = a.get("href", "")
            text = a.get_text(" ", strip=True).lower()
            if "attendance" in href.lower() or "attendance" in text:
                attendance_href = href
                break

        if not attendance_href:
            # look into elements attributes
            for elem in soup.find_all(True):
                for attr in ('data-href','data-url','data-target','onclick'):
                    val = elem.get(attr)
                    if val and 'attendance' in val.lower():
                        attendance_href = val
                        break
                if attendance_href:
                    break

        if not attendance_href:
            attendance_href = "/student/attendance"

        attendance_url = attendance_href if attendance_href.startswith("http") else BASE_URL + (attendance_href if attendance_href.startswith("/") else "/" + attendance_href)
        print("📊 Fetching attendance:", attendance_url)

        att_resp = session.get(attendance_url, headers=headers, timeout=HTTP_TIMEOUT, allow_redirects=True)
        print(f"Attendance GET -> status: {att_resp.status_code}, url: {att_resp.url}")
        print("Attendance preview:", att_resp.text[:HTML_PREVIEW_CHARS].replace("\n", " ")[:HTML_PREVIEW_CHARS])

        if att_resp.status_code == 404:
            combined = login_resp.text + att_resp.text
            endpoints = re.findall(r'(["\'])(\/[^\s"\']*attendance[^\s"\']*)\1', combined, re.I)
            if endpoints:
                candidates = [BASE_URL + ep[1] for ep in endpoints]
                return f"❌ Attendance page 404. Possible endpoints found: {', '.join(candidates[:5])}\nTry calling them with the same session (cookies)."
            return f"❌ Could not access attendance page (Status: 404)."

        if att_resp.status_code != 200:
            return f"❌ Could not access attendance page (Status: {att_resp.status_code}, URL: {att_resp.url})"

        return parse_attendance_html(att_resp.text)

    except requests.exceptions.Timeout:
        return "⏱️ Request timed out. MGIT portal might be slow."
    except requests.exceptions.ConnectionError:
        return "🌐 Connection error. Please check connectivity."
    except Exception as e:
        print("Exception trace:", str(e))
        return f"❌ Error: {str(e)[:200]}\n\nPlease verify credentials."

# -------------------------
# Main
# -------------------------
def main():
    print("\n" + "="*70)
    print("🎓 MGIT ATTENDANCE WHATSAPP BOT (TWILIO) - Full")
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

    # Decide whether to send to user (avoid sending error messages to student)
    error_prefixes = ("❌", "⚠️ Could not extract", "⏱️", "🌐", "⚠️ Could not access", "❌ Selenium fetch failed")
    if any(attendance.startswith(p) for p in error_prefixes):
        print("\nSTEP 2: Fetch failed — not sending attendance to student WhatsApp to avoid confusion.")
        print(f"Reason: {attendance}")
        # Optionally notify developer
        if DEV_WHATSAPP_NUMBER:
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
