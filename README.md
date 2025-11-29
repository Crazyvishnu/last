# 🎓 MGIT Attendance WhatsApp Bot

Automated attendance notifications sent to WhatsApp at 8 AM and 4 PM IST daily.

## ⏰ Schedule
- **8:00 AM IST** - Morning attendance update
- **4:00 PM IST** - Evening attendance update

## 🚀 Features
- ✅ Fully automated using GitHub Actions
- ✅ WhatsApp Business API integration
- ✅ Free to run (GitHub Actions free tier)
- ✅ Secure (credentials stored as GitHub Secrets)
- ✅ No server required

## 📋 Setup Instructions

### 1. Fork/Create this repository (PRIVATE recommended)

### 2. Get WhatsApp Business API Credentials
1. Go to https://developers.facebook.com
2. Create an app → Select Business → Add WhatsApp
3. Copy these credentials:
   - App ID
   - App Secret
   - Phone Number ID
   - Access Token

### 3. Add GitHub Secrets

Go to: **Settings → Secrets and variables → Actions → New repository secret**

Add these **7 secrets**:

| Secret Name | Description | Example |
|------------|-------------|---------|
| `WHATSAPP_APP_ID` | Your WhatsApp App ID | 123456789012345 |
| `WHATSAPP_APP_SECRET` | Your App Secret | abc123def456... |
| `WHATSAPP_PHONE_NUMBER_ID` | Phone Number ID | 109876543210987 |
| `WHATSAPP_ACCESS_TOKEN` | Access Token | EAABsb... |
| `YOUR_WHATSAPP_NUMBER` | Your phone number | 919876543210 |
| `MGIT_USERNAME` | Your MGIT roll number | 25265A0525 |
| `MGIT_PASSWORD` | Your MGIT password | your_password |

**Important:** 
- `YOUR_WHATSAPP_NUMBER` format: Country code + number (no + or spaces)
- Example: `919876543210` ✅ NOT `+91 9876543210` ❌

### 4. Enable GitHub Actions
1. Go to **Actions** tab
2. Click "I understand my workflows, go ahead and enable them"

### 5. Test Manually
1. Go to **Actions** tab
2. Click **"MGIT Attendance Bot"**
3. Click **"Run workflow"** → **"Run workflow"**
4. Wait 30-60 seconds
5. Check your WhatsApp! 📱

## 📊 Message Format
