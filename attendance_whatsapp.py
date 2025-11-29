import requests
from bs4 import BeautifulSoup
import os
from datetime import datetime
import re
from twilio.rest import Client

# Twilio Credentials (from GitHub Secrets)
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
TWILIO_WHATSAPP_FROM = os.environ.get('TWILIO_WHATSAPP_FROM')  # whatsapp:+14155238886
YOUR_WHATSAPP_NUMBER = os.environ.get('YOUR_WHATSAPP_NUMBER')  # whatsapp:+919876543210

# MGIT Credentials
MGIT_USERNAME = os.environ.get('MGIT_USERNAME')
MGIT_PASSWORD = os.environ.get('MGIT_PASSWORD')

BASE_URL = "https://mgit.winnou.net"

def send_whatsapp_message(message):
    """Send message via Twilio WhatsApp"""
    try:
        # Validate credentials
        if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM, YOUR_WHATSAPP_NUMBER]):
            print("❌ Missing Twilio credentials!")
            print(f"   SID: {'✓' if TWILIO_ACCOUNT_SID else '✗'}")
            print(f"   Token: {'✓' if TWILIO_AUTH_TOKEN else '✗'}")
            print(f"   From: {'✓' if TWILIO_WHATSAPP_FROM else '✗'}")
            print(f"   To: {'✓' if YOUR_WHATSAPP_NUMBER else '✗'}")
            return False
        
        print(f"📱 Twilio SID: {TWILIO_ACCOUNT_SID[:10]}...")
        print(f"📤 From: {TWILIO_WHATSAPP_FROM}")
        print(f"📥 To: {YOUR_WHATSAPP_NUMBER}")
        
        # Create Twilio client
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        
        # Send message
        msg = client.messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            body=message,
            to=YOUR_WHATSAPP_NUMBER
        )
        
        print(f"✅ WhatsApp sent successfully!")
        print(f"   Message SID: {msg.sid}")
        print(f"   Status: {msg.status}")
        return True
        
    except Exception as e:
        print(f"❌ Twilio Error: {e}")
        print("\n💡 Common fixes:")
        print("   1. Check TWILIO_WHATSAPP_FROM format: whatsapp:+14155238886")
        print("   2. Check YOUR_WHATSAPP_NUMBER format: whatsapp:+919876543210")
        print("   3. Verify you joined Twilio sandbox: Send 'join <code>' to +14155238886")
        print("   4. Check Account SID and Auth Token are correct")
        return False

def get_attendance():
    """Fetch attendance from MGIT portal"""
    try:
        session = requests.Session()
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        
        print("📡 Accessing MGIT portal...")
        response = session.get(BASE_URL, headers=headers, timeout=20)
        
        if response.status_code != 200:
            return "❌ Cannot reach MGIT portal. Please try again later."
        
        print("✅ Portal accessible")
        
        # Parse login page
        soup = BeautifulSoup(response.text, 'html.parser')
        form = soup.find('form')
        
        # Collect hidden fields (CSRF tokens, etc.)
        hidden_fields = {}
        if form:
            for inp in form.find_all('input', type='hidden'):
                name = inp.get('name')
                value = inp.get('value')
                if name:
                    hidden_fields[name] = value
        
        print(f"🔐 Logging in as: {MGIT_USERNAME}")
        
        # Prepare login data with multiple field name variations
        login_data = {
            'username': MGIT_USERNAME,
            'password': MGIT_PASSWORD,
            'user': MGIT_USERNAME,
            'userid': MGIT_USERNAME,
            'user_id': MGIT_USERNAME,
            'rollno': MGIT_USERNAME,
            'roll_no': MGIT_USERNAME,
            'studentid': MGIT_USERNAME,
            'student_id': MGIT_USERNAME,
            'login': MGIT_USERNAME,
            'uname': MGIT_USERNAME,
            'passwd': MGIT_PASSWORD,
            'pwd': MGIT_PASSWORD,
            'pass': MGIT_PASSWORD,
            'user_pass': MGIT_PASSWORD,
            **hidden_fields
        }
        
        # Find form action URL
        action = form.get('action', '/login') if form else '/login'
        login_url = BASE_URL + action if not action.startswith('http') else action
        
        # Submit login
        login_resp = session.post(
            login_url,
            data=login_data,
            headers=headers,
            timeout=20,
            allow_redirects=True
        )
        
        print(f"Login response: {login_resp.status_code}")
        
        # Check for login success
        if 'invalid' in login_resp.text.lower() or 'incorrect' in login_resp.text.lower():
            return "❌ Login failed! Check your MGIT username and password."
        
        # Find attendance page
        soup = BeautifulSoup(login_resp.text, 'html.parser')
        attendance_url = None
        
        for link in soup.find_all('a', href=True):
            href = link.get('href', '').lower()
            text = link.get_text().lower()
            if 'attendance' in href or 'attendance' in text:
                attendance_url = link.get('href')
                print(f"Found attendance link: {attendance_url}")
                break
        
        if not attendance_url:
            attendance_url = '/student/attendance'
        
        if not attendance_url.startswith('http'):
            attendance_url = BASE_URL + attendance_url
        
        print(f"📊 Fetching attendance: {attendance_url}")
        
        # Get attendance page
        att_resp = session.get(attendance_url, headers=headers, timeout=20)
        
        if att_resp.status_code != 200:
            return f"❌ Could not access attendance page (Status: {att_resp.status_code})"
        
        # Parse attendance data
        soup = BeautifulSoup(att_resp.text, 'html.parser')
        attendance_data = []
        
        print("Parsing attendance data...")
        
        # Method 1: Find spans with percentages (MGIT Winnou specific)
        spans = soup.find_all('span')
        for span in spans:
            text = span.get_text(strip=True)
            onclick = span.get('onclick', '')
            
            # Look for percentage: (74.6) or similar
            pct_match = re.search(r'\((\d+\.?\d*)\)', text)
            
            if pct_match and onclick:
                percentage = float(pct_match.group(1))
                
                # Try to find subject name
                parent = span.find_parent()
                subject = "Subject"
                
                if parent:
                    # Look in parent for subject name
                    for elem in parent.find_all(['span', 'td', 'div', 'label', 'strong', 'b']):
                        elem_text = elem.get_text(strip=True)
                        # Filter out just numbers or percentages
                        if elem_text and not re.match(r'^\(?\d+\.?\d*\)?%?$', elem_text):
                            if len(elem_text) > 3 and elem_text != text:
                                subject = elem_text[:50]
                                break
                
                attendance_data.append({
                    'subject': subject,
                    'percentage': percentage
                })
        
        print(f"Method 1 found: {len(attendance_data)} subjects")
        
        # Method 2: Find tables with attendance
        if not attendance_data:
            print("Trying Method 2: Tables...")
            for table in soup.find_all('table'):
                rows = table.find_all('tr')
                for row in rows[1:]:  # Skip header
                    cols = row.find_all(['td', 'th'])
                    if len(cols) >= 2:
                        subject = cols[0].get_text(strip=True)
                        last_col = cols[-1].get_text(strip=True)
                        
                        # Extract percentage
                        pct_match = re.search(r'(\d+\.?\d*)\s*%?', last_col)
                        if pct_match and subject and len(subject) > 2:
                            try:
                                attendance_data.append({
                                    'subject': subject[:50],
                                    'percentage': float(pct_match.group(1))
                                })
                            except:
                                continue
            
            print(f"Method 2 found: {len(attendance_data)} subjects")
        
        # Method 3: Regex pattern matching
        if not attendance_data:
            print("Trying Method 3: Text patterns...")
            text = soup.get_text()
            matches = re.findall(r'([A-Za-z\s&]+?)[\s:-]+(\d+\.?\d*)\s*%', text)
            
            for subject, pct in matches[:15]:
                subject = subject.strip()
                if len(subject) > 3:
                    try:
                        attendance_data.append({
                            'subject': subject[:50],
                            'percentage': float(pct)
                        })
                    except:
                        continue
            
            print(f"Method 3 found: {len(attendance_data)} subjects")
        
        # Format WhatsApp message
        if attendance_data:
            # Remove duplicates
            seen = set()
            unique = []
            for item in attendance_data:
                key = f"{item['subject']}-{item['percentage']}"
                if key not in seen:
                    seen.add(key)
                    unique.append(item)
            
            attendance_data = unique[:20]  # Limit to 20 subjects
            
            print(f"✅ Final attendance data: {len(attendance_data)} subjects")
            
            # Build message
            message = "📚 *MGIT Attendance Report*\n"
            message += f"⏰ {datetime.now().strftime('%d-%b-%Y %I:%M %p')} IST\n"
            message += f"👤 {MGIT_USERNAME}\n"
            message += "━━━━━━━━━━━━━━━━━━\n\n"
            
            for item in attendance_data:
                pct = item['percentage']
                subject = item['subject']
                
                # Status emoji
                if pct >= 75:
                    emoji = "✅"
                elif pct >= 65:
                    emoji = "⚠️"
                else:
                    emoji = "🔴"
                
                message += f"{emoji} *{subject}*: {pct}%\n"
            
            # Calculate average
            avg = sum(item['percentage'] for item in attendance_data) / len(attendance_data)
            
            message += f"\n━━━━━━━━━━━━━━━━━━\n"
            message += f"📊 Average: {avg:.1f}%\n"
            message += "✅ ≥75% | ⚠️ 65-74% | 🔴 <65%"
            
            return message
        else:
            print("⚠️ No attendance data found")
            return "⚠️ Could not extract attendance data. Please check the portal manually."
    
    except requests.exceptions.Timeout:
        return "⏱️ Request timed out. MGIT portal might be slow. Will retry at next scheduled time."
    except requests.exceptions.ConnectionError:
        return "🌐 Connection error. Please check connectivity."
    except Exception as e:
        error_msg = str(e)
        print(f"Exception: {error_msg}")
        return f"❌ Error: {error_msg[:200]}\n\nPlease verify credentials."

def main():
    """Main execution"""
    print("\n" + "="*70)
    print("🎓 MGIT ATTENDANCE WHATSAPP BOT (TWILIO)")
    print("="*70)
    print(f"⏰ Execution: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} IST")
    print(f"👤 User: {MGIT_USERNAME}")
    print(f"📱 WhatsApp: {YOUR_WHATSAPP_NUMBER}")
    print("="*70 + "\n")
    
    # Step 1: Fetch attendance
    print("STEP 1: Fetching attendance from MGIT portal...")
    print("-"*70)
    attendance = get_attendance()
    print("-"*70)
    
    # Step 2: Send to WhatsApp
    print("\nSTEP 2: Sending to WhatsApp via Twilio...")
    print("-"*70)
    success = send_whatsapp_message(attendance)
    print("-"*70)
    
    # Summary
    print("\n" + "="*70)
    if success:
        print("✅ SUCCESS! Message sent to WhatsApp")
        print(f"   Check your WhatsApp: {YOUR_WHATSAPP_NUMBER}")
    else:
        print("⚠️ FAILED! Check error messages above")
        print("\n📝 Troubleshooting:")
        print("   1. Verify you joined Twilio sandbox")
        print("   2. Check all WhatsApp numbers have 'whatsapp:' prefix")
        print("   3. Verify Account SID and Auth Token")
    print("="*70 + "\n")

if __name__ == "__main__":
    main()
