#!/usr/bin/env python3
"""
discover_attendance_endpoint.py

Login -> dump all logged-in links, data-* attrs, inline scripts,
search for 'attendance' occurrences and probe candidate URLs.

Requires same env vars as your bot:
 - MGIT_USERNAME
 - MGIT_PASSWORD
 - BASE_URL (optional, defaults to https://mgit.winnou.net)
"""

import os, re, time, requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE_URL = os.environ.get('BASE_URL', 'https://mgit.winnou.net').rstrip('/')
MGIT_USERNAME = os.environ.get('MGIT_USERNAME')
MGIT_PASSWORD = os.environ.get('MGIT_PASSWORD')

HTTP_TIMEOUT = 20

if not MGIT_USERNAME or not MGIT_PASSWORD:
    print("Please set MGIT_USERNAME and MGIT_PASSWORD environment variables before running.")
    raise SystemExit(1)

def auto_login(session, headers):
    # GET base
    r0 = session.get(BASE_URL, headers=headers, timeout=HTTP_TIMEOUT, allow_redirects=True)
    print("Initial GET ->", r0.status_code, r0.url)
    soup = BeautifulSoup(r0.text, 'html.parser')
    form = soup.find('form') or soup.find('form', attrs={'id':'login-form'}) or soup.find('form', attrs={'id':'mod-login-form'})
    hidden = {}
    if form:
        for inp in form.find_all('input'):
            name = inp.get('name')
            if not name:
                continue
            typ = (inp.get('type') or 'text').lower()
            val = inp.get('value', '')
            if typ == 'password':
                hidden[name] = MGIT_PASSWORD
            elif typ in ('text','email'):
                lname = name.lower()
                if any(x in lname for x in ('user','roll','id','uname','email')):
                    hidden[name] = MGIT_USERNAME
                elif val:
                    hidden[name] = val
            else:
                hidden[name] = val
        action = form.get('action') if form else '/index.php'
        login_url = action if action.startswith('http') else urljoin(BASE_URL + '/', action)
    else:
        print("⚠️ No form found; falling back to /index.php")
        login_url = BASE_URL + '/index.php'
        hidden = {'username': MGIT_USERNAME, 'password': MGIT_PASSWORD}

    headers['Referer'] = r0.url
    print("POSTing to:", login_url)
    print("Payload keys:", list(hidden.keys()))
    resp = session.post(login_url, data=hidden, headers=headers, timeout=HTTP_TIMEOUT, allow_redirects=True)
    print("Login POST ->", resp.status_code, resp.url)
    return resp

def extract_candidates(html):
    soup = BeautifulSoup(html, 'html.parser')
    # 1) all anchor hrefs
    hrefs = []
    for a in soup.find_all('a', href=True):
        hrefs.append((a.get_text(" ", strip=True), a['href']))
    # 2) data-* attributes that may contain URLs
    data_vals = []
    for el in soup.find_all(True):
        for attr, val in el.attrs.items():
            if attr.startswith('data-') and isinstance(val, str) and 'attendance' in val.lower():
                data_vals.append((attr, val))
    # 3) find inline scripts containing 'attendance' or likely endpoints
    scripts = []
    for s in soup.find_all('script'):
        txt = ''
        if s.get('src'):
            scripts.append(('src', s.get('src')))
        elif s.string:
            if 'attendance' in s.string.lower() or 'xhr' in s.string.lower():
                scripts.append(('inline', s.string.strip()[:800]))
    # 4) search whole text for /...attendance... endpoints
    raw_matches = re.findall(r'["\'](\/[^"\']*attendance[^"\']*)["\']', html, re.I)
    raw_matches = list(dict.fromkeys(raw_matches))  # unique preserve order
    return hrefs, data_vals, scripts, raw_matches

def probe_candidates(session, headers, candidates):
    print("\nProbing candidate URLs (showing status and small preview):")
    seen = set()
    for path in candidates:
        if not path:
            continue
        full = path if path.startswith('http') else urljoin(BASE_URL + '/', path)
        if full in seen:
            continue
        seen.add(full)
        try:
            r = session.get(full, headers=headers, timeout=HTTP_TIMEOUT, allow_redirects=True)
            print(f"[{r.status_code}] {full}")
            txt = r.text.replace('\n',' ')[:800]
            print(" Preview:", txt[:300], "...\n")
        except Exception as e:
            print(f"[ERR] {full} -> {e}")

def main():
    session = requests.Session()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    login_resp = auto_login(session, headers)
    html = login_resp.text
    print("\n--- Extracting candidate links/data/script fragments containing 'attendance' ---\n")
    hrefs, data_vals, scripts, raw_matches = extract_candidates(html)

    print("Found anchor hrefs (first 50):")
    for i,(txt, href) in enumerate(hrefs[:50], 1):
        print(f"{i:02d}. text='{txt[:40]}', href='{href}'")

    print("\nFound data-* attributes containing 'attendance':")
    for attr, val in data_vals:
        print(f" {attr} = {val}")

    print("\nFound script fragments or src mentioning attendance/XHR (first 10):")
    for typ, val in scripts[:10]:
        label = "(src)" if typ=='src' else "(inline)"
        print(f" {label} -> {val[:200].replace('\\n',' ')}")

    print("\nRaw JS-found relative endpoints (from regex):")
    for m in raw_matches:
        print(" ", m)

    # Build candidate probing list
    candidates = set()
    # Add raw matches and hrefs
    for _, href in hrefs:
        candidates.add(href)
    for _, val in data_vals:
        candidates.add(val)
    for m in raw_matches:
        candidates.add(m)
    # Add common Joomla/onEdu patterns to try
    common = [
        '/student/attendance', '/index.php?option=com_attendance', '/index.php?option=com_user&view=attendance',
        '/index.php?option=com_onedu&view=attendance', '/index.php?option=com_students&view=attendance',
        '/index.php?option=com_onesite&view=attendance', '/attendance', '/students/attendance',
        '/components/com_attendance/views/attendance/tmpl/default.php', '/index.php?option=com_reports&view=attendance'
    ]
    for c in common:
        candidates.add(c)

    # probe them
    probe_candidates(session, headers, list(candidates))

    # Also print cookies (may help)
    print("\nSession cookies after login:")
    print(session.cookies.get_dict())

    print("\nDone. Copy the most promising 200-char previews above and paste here if you want me to pick the exact endpoint and adapt the bot.")

if __name__ == "__main__":
    main()
