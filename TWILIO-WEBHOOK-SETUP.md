# Twilio Webhook Configuration Guide

## Step-by-Step Instructions

### 1. Get Your ngrok URL

Your ngrok URL should be visible in the ngrok terminal window. It will look like:
```
https://abc123.ngrok.io
```

**OR** open http://localhost:4040 in your browser to see the ngrok dashboard with your URL.

### 2. Configure Twilio Webhooks

1. **Go to Twilio Console**: https://console.twilio.com

2. **Navigate to Phone Numbers**:
   - Click on **Phone Numbers** in the left sidebar
   - Click **Manage** → **Active Numbers**

3. **Select Your Number**:
   - Click on your phone number: **+1 (925) 481-5386**

4. **Configure Voice Webhooks**:
   - Scroll down to the **Voice & Fax** section
   
   - **A CALL COMES IN** webhook:
     - Paste your ngrok URL + `/api/phone/incoming`
     - Example: `https://abc123.ngrok.io/api/phone/incoming`
     - Set HTTP method to: **POST**
   
   - **CALL STATUS CHANGES** webhook:
     - Paste your ngrok URL + `/api/phone/status`
     - Example: `https://abc123.ngrok.io/api/phone/status`
     - Set HTTP method to: **POST**

5. **Save Configuration**:
   - Click **Save** at the bottom of the page

### 3. Test Your Setup

1. Make sure:
   - ✅ Backend is running on port 8000
   - ✅ ngrok is running and forwarding to port 8000
   - ✅ Webhooks are configured in Twilio

2. **Call your number**: **+1 (925) 481-5386**

3. You should hear the AI receptionist greeting!

## Troubleshooting

### "Invalid URL" error in Twilio
- Make sure you're using the **HTTPS** URL (not HTTP)
- Make sure ngrok is running
- Check that the URL format is correct: `https://abc123.ngrok.io/api/phone/incoming`

### "Webhook timeout" error
- Make sure your backend is running
- Check that ngrok is forwarding to the correct port (8000)
- Verify the backend endpoint is accessible

### Still hearing default Twilio message
- Double-check webhook URLs are saved
- Wait a few seconds after saving and try calling again
- Check backend logs for incoming requests

## Important Notes

- **Keep ngrok running** while testing - if you close it, the URL changes
- **Keep backend running** on port 8000
- The ngrok URL changes each time you restart ngrok (unless you have a paid plan with a static domain)


