import requests
from bs4 import BeautifulSoup
import os
from datetime import datetime
import re

# WhatsApp Business API Credentials
WHATSAPP_APP_ID = os.environ.get('WHATSAPP_APP_ID')
WHATSAPP_APP_SECRET = os.environ.get('WHATSAPP_APP_SECRET')
WHATSAPP_PHONE_NUMBER_ID = os.environ.get('WHATSAPP_PHONE_NUMBER_ID')
WHATSAPP_ACCESS_TOKEN = os.environ.get('WHATSAPP_ACCESS_TOKEN')
YOUR_WHATSAPP_NUMBER = os.environ.get('YOUR_WHATSAPP_NUMBER')

# MGIT Credentials
MGIT_USERNAME = os.environ.get('MGIT_USERNAME')
MGIT_PASSWORD = os.environ.get('MGIT_PASSWORD')

BASE_URL = "https://mgit.winnou.net"
WHATSAPP_API_URL = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"

def send_whatsapp_message(message):
    """Send message via WhatsApp Business API"""
    try:
        headers = {
            'Authorization': f'Bearer {WHATSAPP_ACCESS_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": YOUR_WHATSAPP_NUMBER,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": message
            }
        }
        
        response = requests.post(WHATSAPP_API_URL, headers=headers, json=payload, timeout=15)
        
        if response.status_code == 200:
            result = response.json()
            msg_id = result.get('messages', [{}])[0].get('id', 'N/A')
            print(f"✅ WhatsApp sent! Message ID: {msg_id}")
            return True
        else:
            print(f"❌ Failed: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def get_attendance():
    """Fetch attendance from MGIT portal"""
    try:
        session = requests.Session()
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        }
        
        print("📡 Accessing MGIT portal...")
        response = session.get(BASE_URL, headers=headers, timeout=20)
        
        if response.status_code != 200:
            return "❌ Cannot reach MGIT portal"
        
        soup = BeautifulSoup(response.text, 'html.parser')
        form = soup.find('form')
        
        # Collect hidden fields
        hidden_fields = {}
        if form:
            for inp in form.find_all('input', type='hidden'):
                name = inp.get('name')
                value = inp.get('value')
                if name:
                    hidden_fields[name] = value
        
        print(f"🔐 Logging in: {MGIT_USERNAME}")
        
        # Login data with multiple field variations
        login_data = {
            'username': MGIT_USERNAME,
            'password': MGIT_PASSWORD,
            'user': MGIT_USERNAME,
            'userid': MGIT_USERNAME,
            'user_id': MGIT_USERNAME,
            'rollno': MGIT_USERNAME,
            'roll_no': MGIT_USERNAME,
            'studentid': MGIT_USERNAME,
            'login': MGIT_USERNAME,
            'passwd': MGIT_PASSWORD,
            'pwd': MGIT_PASSWORD,
            'pass': MGIT_PASSWORD,
            **hidden_fields
        }
        
        # Get form action
        action = form.get('action', '/login') if form else '/login'
        login_url = BASE_URL + action if not action.startswith('http') else action
        
        # Submit login
        login_resp = session.post(login_url, data=login_data, headers=headers, timeout=20, allow_redirects=True)
        
        print(f"Login: {login_resp.status_code}")
        
        # Find attendance page
        soup = BeautifulSoup(login_resp.text, 'html.parser')
        attendance_url = None
        
        for link in soup.find_all('a', href=True):
            href = link.get('href', '').lower()
            text = link.get_text().lower()
            if 'attendance' in href or 'attendance' in text:
                attendance_url = link.get('href')
                break
        
        if not attendance_url:
            attendance_url = '/student/attendance'
        
        attendance_url = BASE_URL + attendance_url if not attendance_url.startswith('http') else attendance_url
        
        print(f"📊 Fetching: {attendance_url}")
        att_resp = session.get(attendance_url, headers=headers, timeout=20)
        
        # Parse attendance
        soup = BeautifulSoup(att_resp.text, 'html.parser')
        attendance_data = []
        
        # Method 1: Span tags with percentages
        spans = soup.find_all('span')
        for span in spans:
            text = span.get_text(strip=True)
            onclick = span.get('onclick', '')
            
            pct_match = re.search(r'\((\d+\.?\d*)\)', text)
            if pct_match and onclick:
                percentage = float(pct_match.group(1))
                
                # Find subject name
                parent = span.find_parent()
                subject = "Subject"
                
                if parent:
                    for elem in parent.find_all(['span', 'td', 'div', 'label']):
                        elem_text = elem.get_text(strip=True)
                        if elem_text and not re.match(r'^\(?\d+\.?\d*\)?%?$', elem_text) and len(elem_text) > 3:
                            subject = elem_text[:50]
                            break
                
                attendance_data.append({'subject': subject, 'percentage': percentage})
        
        # Method 2: Tables
        if not attendance_data:
            for table in soup.find_all('table'):
                rows = table.find_all('tr')
                for row in rows[1:]:
                    cols = row.find_all(['td', 'th'])
                    if len(cols) >= 2:
                        subject = cols[0].get_text(strip=True)
                        last_col = cols[-1].get_text(strip=True)
                        pct_match = re.search(r'(\d+\.?\d*)\s*%?', last_col)
                        if pct_match and subject and len(subject) > 2:
                            attendance_data.append({
                                'subject': subject[:50],
                                'percentage': float(pct_match.group(1))
                            })
        
        # Method 3: Text patterns
        if not attendance_data:
            text = soup.get_text()
            matches = re.findall(r'([A-Za-z\s&]+?)[\s:-]+(\d+\.?\d*)\s*%', text)
            for subject, pct in matches[:15]:
                if len(subject.strip()) > 3:
                    attendance_data.append({
                        'subject': subject.strip()[:50],
                        'percentage': float(pct)
                    })
        
        # Format message
        if attendance_data:
            # Remove duplicates
            seen = set()
            unique = []
            for item in attendance_data:
                key = f"{item['subject']}-{item['percentage']}"
                if key not in seen:
                    seen.add(key)
                    unique.append(item)
            
            attendance_data = unique[:20]
            
            message = "📚 *MGIT Attendance Report*\n"
            message += f"⏰ {datetime.now().strftime('%d-%b-%Y %I:%M %p')} IST\n"
            message += f"👤 {MGIT_USERNAME}\n"
            message += "━━━━━━━━━━━━━━━━━━\n\n"
            
            for item in attendance_data:
                pct = item['percentage']
                subject = item['subject']
                
                if pct >= 75:
                    emoji = "✅"
                elif pct >= 65:
                    emoji = "⚠️"
                else:
                    emoji = "🔴"
                
                message += f"{emoji} {subject}: {pct}%\n"
            
            avg = sum(i['percentage'] for i in attendance_data) / len(attendance_data)
            message += f"\n━━━━━━━━━━━━━━━━━━\n"
            message += f"📊 Average: {avg:.1f}%\n"
            message += "✅ ≥75% | ⚠️ 65-74% | 🔴 <65%"
            
            return message
        else:
            return "⚠️ Could not extract attendance. Check portal manually."
    
    except Exception as e:
        return f"❌ Error: {str(e)[:200]}"

def main():
    print("\n" + "="*70)
    print("🎓 MGIT ATTENDANCE BOT")
    print("="*70)
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} IST")
    print(f"👤 {MGIT_USERNAME}")
    print("="*70 + "\n")
    
    print("STEP 1: Fetching attendance...")
    attendance = get_attendance()
    
    print("\nSTEP 2: Sending WhatsApp...")
    success = send_whatsapp_message(attendance)
    
    print("\n" + "="*70)
    print("✅ SUCCESS!" if success else "⚠️ FAILED!")
    print("="*70 + "\n")

if __name__ == "__main__":
    main()
