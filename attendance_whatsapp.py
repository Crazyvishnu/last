#!/usr/bin/env python3
"""
attendance_whatsapp.py

Complete ready-to-run bot:
- Auto-detect login form & submit
- Fetch attendance and format WhatsApp message
- Discovery mode (DISCOVER=1) to find endpoints if attendance page missing
- Optional Selenium fallback (USE_SELENIUM=1)
"""

import os
import re
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from twilio.rest import Client

# -------------------------
# Config & environment
# -------------------------
# Use default when env var is missing or empty
BASE_URL = (os.environ.get('BASE_URL') or "https://mgit.winnou.net").rstrip('/')
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
TWILIO_WHATSAPP_FROM = os.environ.get('TWILIO_WHATSAPP_FROM')  # whatsapp:+14155238886
YOUR_WHATSAPP_NUMBER = os.environ.get('YOUR_WHATSAPP_NUMBER')  # whatsapp:+91XXXXXXXXXX
DEV_WHATSAPP_NUMBER = os.environ.get('DEV_WHATSAPP_NUMBER')    # optional debug recipient
MGIT_USERNAME = os.environ.get('MGIT_USERNAME')
MGIT_PASSWORD = os.environ.get('MGIT_PASSWORD')

HTTP_TIMEOUT = int(os.environ.get('HTTP_TIMEOUT', '20'))
HTML_PREVIEW_CHARS = int(os.environ.get('HTML_PREVIEW_CHARS', '800'))
USE_SELENIUM = os.environ.get('USE_SELENIUM', '0').lower() in ('1', 'true', 'yes', 'y')
DISCOVER_MODE = os.environ.get('DISCOVER', '0').lower() in ('1', 'true', 'yes', 'y')

# optional selenium imports
if USE_SELENIUM:
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
    except Exception as e:
        print("⚠️ Selenium requested but not installed or import failed:", e)
        USE_SELENIUM = False

# -------------------------
# Twilio helper
# -------------------------
def send_whatsapp_message(message, to_number=None):
    if to_number is None:
        to_number = YOUR_WHATSAPP_NUMBER
    try:
        if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM, to_number]):
            print("❌ Missing Twilio configuration; cannot send WhatsApp.")
            return False
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        msg = client.messages.create(from_=TWILIO_WHATSAPP_FROM, body=message, to=to_number)
        print("✅ WhatsApp sent. SID:", getattr(msg, "sid", "N/A"))
        return True
    except Exception as e:
        print("❌ Twilio send error:", e)
        return False

# -------------------------
# Selenium fallback
# -------------------------
def fetch_with_selenium(path="/student/attendance", login_path="/index.php"):
    if not USE_SELENIUM:
        raise RuntimeError("Selenium not enabled.")
    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=opts)
    try:
        # open login
        login_url = login_path if login_path.startswith("http") else BASE_URL + login_path
        driver.get(login_url)
        time.sleep(2)
        # try common selectors
        try:
            usr = driver.find_element(By.NAME, "username")
        except:
            usr = None
            for n in ("username","user","userid","rollno","email"):
                try:
                    usr = driver.find_element(By.NAME, n)
                    break
                except:
                    pass
        try:
            pwd = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
        except:
            pwd = None
            for n in ("password","passwd","pwd"):
                try:
                    pwd = driver.find_element(By.NAME, n)
                    break
                except:
                    pass
        if not usr or not pwd:
            raise RuntimeError("Could not find username/password inputs in Selenium.")
        usr.clear(); usr.send_keys(MGIT_USERNAME)
        pwd.clear(); pwd.send_keys(MGIT_PASSWORD)
        # submit
        try:
            driver.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        except:
            pwd.send_keys("\n")
        time.sleep(3)
        # go to attendance
        target = path if path.startswith("http") else BASE_URL + path
        driver.get(target)
        time.sleep(2)
        return driver.page_source
    finally:
        try:
            driver.quit()
        except:
            pass

# -------------------------
# Parse HTML to attendance message
# -------------------------
def parse_attendance_html(html_text):
    soup = BeautifulSoup(html_text, "html.parser")
    attendance_data = []

    # Strategy A: look for elements with percentages
    for elem in soup.find_all(['span','td','th','div','label','li']):
        try:
            text = elem.get_text(" ", strip=True)
        except:
            continue
        if not text or len(text) > 400:
            continue
        if '%' not in text and 'attendance' not in text.lower() and not re.search(r'\d{1,3}\.?\d*\s*$', text):
            continue
        m = re.search(r'(\d{1,3}\.?\d*)\s*%?', text)
        if m:
            try:
                pct = float(m.group(1))
            except:
                continue
            # guess subject name from nearby markup
            subj = None
            parent = elem.find_parent()
            if parent:
                strong = parent.find(['strong','b'])
                if strong and strong.get_text(strip=True):
                    subj = strong.get_text(strip=True)
                else:
                    prev = elem.find_previous(string=True)
                    if prev and isinstance(prev, str):
                        pt = prev.strip()
                        if pt and not re.match(r'^\d', pt):
                            subj = pt[:50]
            attendance_data.append({'subject': subj or 'Subject', 'percentage': pct})

    # Strategy B: table fallback
    if not attendance_data:
        for table in soup.find_all('table'):
            rows = table.find_all('tr')
            for row in rows[1:]:
                cols = [c.get_text(" ", strip=True) for c in row.find_all(['td','th'])]
                if len(cols) >= 2:
                    last = cols[-1]
                    m = re.search(r'(\d{1,3}\.?\d*)\s*%?', last)
                    if m:
                        try:
                            attendance_data.append({'subject': cols[0][:50], 'percentage': float(m.group(1))})
                        except:
                            pass

    # Strategy C: regex fallback on page text
    if not attendance_data:
        text = soup.get_text(" ", strip=True)
        matches = re.findall(r'([A-Za-z0-9\-\&\s]{4,80})[:\-\s]{1,4}(\d{1,3}\.?\d*)\s*%', text)
        for subj, pct in matches[:20]:
            attendance_data.append({'subject': subj.strip()[:50], 'percentage': float(pct)})

    if not attendance_data:
        return "⚠️ Could not extract attendance data. Page layout changed or site uses JS/XHR."

    # dedupe
    seen = set(); unique = []
    for it in attendance_data:
        key = f"{it['subject']}-{it['percentage']}"
        if key not in seen:
            seen.add(key); unique.append(it)
    attendance_data = unique[:20]

    # build message
    message = "📚 *MGIT Attendance Report*\n"
    message += f"⏰ {datetime.now().strftime('%d-%b-%Y %I:%M %p')} IST\n"
    message += f"👤 {MGIT_USERNAME}\n"
    message += "━━━━━━━━━━━━━━━━━━\n\n"
    for it in attendance_data:
        pct = it['percentage']; subj = it['subject']
        emoji = "✅" if pct >= 75 else ("⚠️" if pct >= 65 else "🔴")
        message += f"{emoji} *{subj}*: {pct}%\n"
    avg = sum(i['percentage'] for i in attendance_data) / len(attendance_data)
    message += f"\n━━━━━━━━━━━━━━━━━━\n📊 Average: {avg:.1f}%\n✅ ≥75% | ⚠️ 65-74% | 🔴 <65%"
    return message

# -------------------------
# Discovery helper (prints anchors, script snippets, probes)
# -------------------------
def discovery_dump(session, headers):
    r0 = session.get(BASE_URL, headers=headers, timeout=HTTP_TIMEOUT, allow_redirects=True)
    soup = BeautifulSoup(r0.text, "html.parser")
    # anchors
    anchors = [(a.get_text(" ",strip=True), a.get('href')) for a in soup.find_all('a', href=True)]
    print("\nFound anchor hrefs (first 50):")
    for i, (t,h) in enumerate(anchors[:50], 1):
        print(f"{i:02d}. text='{(t or '')[:40]}', href='{h}'")
    # data-* attrs
    print("\nFound data-* attributes containing 'attendance':")
    for el in soup.find_all(True):
        for attr, val in getattr(el, 'attrs', {}).items():
            if attr.startswith('data-') and isinstance(val, str) and 'attendance' in val.lower():
                print(f" {attr} = {val}")
    # script fragments
    print("\nFound script fragments mentioning attendance or xhr (first 10):")
    cnt = 0
    for s in soup.find_all('script'):
        if s.get('src'):
            src = s.get('src')
            if 'attendance' in src.lower():
                print(" (src) ->", src[:300])
                cnt += 1
        elif s.string and ('attendance' in s.string.lower() or 'xhr' in s.string.lower()):
            snippet = s.string.strip().replace("\n"," ")[:400]
            print(" (inline) ->", snippet[:300])
            cnt += 1
        if cnt >= 10:
            break
    # raw regex endpoints
    raw = re.findall(r'["\'](\/[^"\']*attendance[^"\']*)["\']', r0.text, re.I)
    raw = list(dict.fromkeys(raw))
    print("\nRaw JS-found relative endpoints:")
    for m in raw:
        print(" ", m)
    # probe common candidates
    candidates = set([h for _,h in anchors if h and 'attendance' in h.lower()])
    candidates.update(raw)
    commons = ['/student/attendance','/attendance','/index.php?option=com_attendance','/index.php?option=com_onedu&task=getAttendance&format=raw']
    for c in commons: candidates.add(c)
    print("\nProbing candidate URLs:")
    for p in candidates:
        if not p: continue
        full = p if p.startswith('http') else (BASE_URL + p if p.startswith('/') else BASE_URL + '/' + p)
        try:
            r = session.get(full, headers=headers, timeout=HTTP_TIMEOUT, allow_redirects=True)
            snippet = (r.text or "")[:300].replace("\n"," ")
            print(f"[{r.status_code}] {full} -> {snippet[:200]} ...")
        except Exception as e:
            print(f"[ERR] {full} -> {e}")
    print("\nSession cookies:", session.cookies.get_dict())

# -------------------------
# Main fetching flow
# -------------------------
def get_attendance():
    # try selenium first if enabled
    if USE_SELENIUM:
        try:
            html = fetch_with_selenium(path="/student/attendance", login_path="/index.php")
            return parse_attendance_html(html)
        except Exception as e:
            print("Selenium fetch failed:", e)
            # fallback to requests

    session = requests.Session()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9'
    }

    try:
        print("📡 Accessing portal base:", BASE_URL)
        r0 = session.get(BASE_URL, headers=headers, timeout=HTTP_TIMEOUT, allow_redirects=True)
        print("Initial GET -> status:", r0.status_code, "url:", r0.url)
        print("Preview:", (r0.text or "")[:HTML_PREVIEW_CHARS].replace("\n"," "))

        if r0.status_code != 200:
            return f"❌ Cannot reach portal (Status: {r0.status_code})"

        # find login form
        soup = BeautifulSoup(r0.text, "html.parser")
        form = soup.find('form') or soup.find('form', attrs={'id':'login-form'}) or soup.find('form', attrs={'id':'mod-login-form'})
        login_payload = {}
        login_url = BASE_URL + "/index.php"
        if form:
            action = form.get('action') or "/index.php"
            login_url = action if action.startswith('http') else (BASE_URL + action if action.startswith('/') else BASE_URL + '/' + action)
            for inp in form.find_all('input'):
                name = inp.get('name')
                if not name: continue
                typ = (inp.get('type') or 'text').lower()
                val = inp.get('value','')
                if typ == 'password':
                    login_payload[name] = MGIT_PASSWORD or val
                elif typ in ('text','email'):
                    lname = name.lower()
                    if any(k in lname for k in ('user','roll','id','uname','email')):
                        login_payload[name] = MGIT_USERNAME or val
                    elif val:
                        login_payload[name] = val
                    else:
                        # fallback assume username
                        if not any(x in k.lower() for k in login_payload.keys()):
                            login_payload[name] = MGIT_USERNAME
                        else:
                            login_payload[name] = val
                elif typ == 'hidden':
                    login_payload[name] = val
                elif typ == 'submit':
                    if val:
                        login_payload[name] = val
                else:
                    if val:
                        login_payload[name] = val
        else:
            # fallback simple login keys
            login_payload = {'username': MGIT_USERNAME, 'passwd': MGIT_PASSWORD}
            login_url = BASE_URL + "/index.php"

        headers['Referer'] = r0.url
        # masked preview for logs (don't print password)
        masked = {}
        for k,v in login_payload.items():
            if 'pass' in k.lower():
                masked[k] = '***'
            else:
                vs = str(v)
                masked[k] = vs if len(vs) < 80 else vs[:60] + '...'
        print("➡️ POSTing login to:", login_url)
        print("➡️ Payload keys:", list(login_payload.keys()))
        print("➡️ Payload preview (masked):", masked)

        login_resp = session.post(login_url, data=login_payload, headers=headers, timeout=HTTP_TIMEOUT, allow_redirects=True)
        print("Login POST -> status:", login_resp.status_code, "url:", login_resp.url)
        print("Login preview:", (login_resp.text or "")[:HTML_PREVIEW_CHARS].replace("\n"," "))

        if login_resp.status_code >= 400:
            return f"❌ Login POST failed (Status: {login_resp.status_code})"
        if any(x in (login_resp.text or "").lower() for x in ("invalid", "incorrect", "unauthorized", "login failed", "please login", "captcha")):
            return "❌ Login failed! Check credentials or site may require JS/captcha."

        # discovery mode?
        if DISCOVER_MODE:
            discovery_dump(session, headers)
            return "ℹ️ Discovery complete. Check logs for candidate endpoints."

        # find attendance link in logged-in HTML
        soup2 = BeautifulSoup(login_resp.text or "", "html.parser")
        attendance_href = None
        for a in soup2.find_all(['a','button'], href=True):
            if a.get_text(" ",strip=True) and 'attendance' in (a.get_text(" ",strip=True).lower() + a.get('href','').lower()):
                attendance_href = a.get('href'); break
        if not attendance_href:
            for el in soup2.find_all(True):
                for attr in ('data-href','data-url','data-target','onclick'):
                    val = el.get(attr)
                    if val and 'attendance' in val.lower():
                        attendance_href = val; break
                if attendance_href:
                    break
        if not attendance_href:
            attendance_href = "/student/attendance"

        if attendance_href.startswith("http"):
            attendance_url = attendance_href
        elif attendance_href.startswith("/"):
            attendance_url = BASE_URL + attendance_href
        else:
            attendance_url = BASE_URL + "/" + attendance_href

        print("📊 Fetching attendance URL:", attendance_url)
        att_resp = session.get(attendance_url, headers=headers, timeout=HTTP_TIMEOUT, allow_redirects=True)
        print("Attendance GET -> status:", att_resp.status_code, "url:", att_resp.url)
        print("Attendance preview:", (att_resp.text or "")[:HTML_PREVIEW_CHARS].replace("\n"," "))

        if att_resp.status_code == 404:
            # try find XHR endpoints inside login_resp/text
            combined = (login_resp.text or "") + (att_resp.text or "")
            endpoints = re.findall(r'["\'](\/[^"\']*attendance[^"\']*)["\']', combined, re.I)
            if endpoints:
                candidates = [BASE_URL + e for e in endpoints[:5]]
                return f"❌ Attendance 404. Possible endpoints: {', '.join(candidates)}"
            return f"❌ Could not access attendance page (Status: 404)."

        if att_resp.status_code != 200:
            return f"❌ Could not access attendance page (Status: {att_resp.status_code})"

        return parse_attendance_html(att_resp.text)

    except requests.exceptions.Timeout:
        return "⏱️ Request timed out."
    except requests.exceptions.ConnectionError:
        return "🌐 Connection error."
    except Exception as e:
        print("Exception trace:", e)
        return f"❌ Error: {str(e)[:200]}"

# -------------------------
# Main entrypoint
# -------------------------
def main():
    print("\n" + "="*60)
    print("🎓 MGIT ATTENDANCE WHATSAPP BOT")
    print("="*60)
    print("Execution:", datetime.now().strftime('%Y-%m-%d %H:%M:%S'), "IST")
    print("User:", MGIT_USERNAME)
    print("WhatsApp:", YOUR_WHATSAPP_NUMBER)
    print("USE_SELENIUM:", USE_SELENIUM, "DISCOVER:", DISCOVER_MODE)
    print("="*60 + "\n")

    result = get_attendance()
    print("\nFetch result (trimmed):")
    print(result[:1500])

    # Only send if result looks like a report (not error markers)
    error_prefixes = ("❌", "⚠️", "⏱️", "🌐", "ℹ️")
    if any(result.startswith(p) for p in error_prefixes):
        print("\nNot sending to student WhatsApp because fetch returned an error/info.")
        # optionally send debug to dev
        if DEV_WHATSAPP_NUMBER and not result.startswith("ℹ️"):
            dbg = f"⚠️ Attendance fetch failed for {MGIT_USERNAME} at {datetime.now().strftime('%d-%b-%Y %I:%M %p')} IST\n\n{result}"
            send_whatsapp_message(dbg, to_number=DEV_WHATSAPP_NUMBER)
        else:
            print("DEV_WHATSAPP_NUMBER not set or discovery run; skipping dev message.")
    else:
        print("\nSending attendance to WhatsApp...")
        ok = send_whatsapp_message(result)
        if ok:
            print("Sent successfully.")
        else:
            print("Failed to send via Twilio. Check Twilio credentials and sandbox status.")
    print("\nRun finished.\n")

if __name__ == "__main__":
    main()
