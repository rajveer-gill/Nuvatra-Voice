# Phone Integration Setup Guide

This guide will help you set up phone call functionality for your Nuvatra Voice receptionist using Twilio.

## Prerequisites

1. **Twilio Account**: Sign up at [twilio.com](https://www.twilio.com/try-twilio)
2. **Twilio Phone Number**: Purchase a phone number from Twilio
3. **Public URL**: Your backend needs to be accessible from the internet (use ngrok for local development)

## Step 1: Install Twilio Dependencies

The Twilio SDK is already in `requirements.txt`. Install it:

```bash
pip install -r requirements.txt
```

## Step 2: Get Twilio Credentials

1. Log in to your [Twilio Console](https://console.twilio.com)
2. Go to **Account** → **API Keys & Tokens**
3. Copy your:
   - **Account SID**
   - **Auth Token**

## Step 3: Purchase a Phone Number

1. In Twilio Console, go to **Phone Numbers** → **Manage** → **Buy a number**
2. Choose a number with **Voice** capability
3. Purchase the number

## Step 4: Configure Environment Variables

Add these to your `backend/.env` file:

```env
# Twilio Configuration
TWILIO_ACCOUNT_SID=your_account_sid_here
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_PHONE_NUMBER=+1234567890  # Your Twilio phone number (with country code)
```

## Step 5: Make Your Backend Publicly Accessible

For local development, use **ngrok** to expose your backend:

### Install ngrok:
- Download from [ngrok.com](https://ngrok.com/download)
- Or install via package manager: `choco install ngrok` (Windows) or `brew install ngrok` (Mac)

### Set up ngrok authentication:
1. **Sign up for a free ngrok account**: Go to [ngrok.com/signup](https://dashboard.ngrok.com/signup)
2. **Get your authtoken**: After signing up, go to [ngrok.com/get-started/your-authtoken](https://dashboard.ngrok.com/get-started/your-authtoken)
3. **Configure ngrok with your authtoken**:
   ```bash
   ngrok config add-authtoken YOUR_AUTHTOKEN_HERE
   ```
   Replace `YOUR_AUTHTOKEN_HERE` with the token from the ngrok dashboard.

### Start ngrok:
```bash
ngrok http 8000
```

This will give you a public URL like: `https://abc123.ngrok.io`

**Important**: Copy this URL - you'll need it for Twilio webhooks!

## Step 6: Configure Twilio Webhooks

1. In Twilio Console, go to **Phone Numbers** → **Manage** → **Active Numbers**
2. Click on your phone number
3. Scroll to **Voice & Fax** section
4. Set the webhook URL:
   - **A CALL COMES IN**: `https://your-ngrok-url.ngrok.io/api/phone/incoming`
   - **CALL STATUS CHANGES**: `https://your-ngrok-url.ngrok.io/api/phone/status`
5. Set HTTP method to **POST**
6. Click **Save**

## Step 7: Test Your Phone Integration

1. Make sure your backend is running:
   ```bash
   cd backend
   python main.py
   ```

2. Make sure ngrok is running (if testing locally)

3. Call your Twilio phone number from any phone

4. You should hear the AI receptionist greeting you!

## How It Works

1. **Incoming Call**: When someone calls your Twilio number, Twilio sends a webhook to `/api/phone/incoming`
2. **Greeting**: The AI plays a greeting using Twilio's TTS
3. **Speech Input**: Twilio's `<Gather>` verb captures the caller's speech
4. **AI Processing**: The speech is sent to OpenAI GPT-4 for processing
5. **Response**: The AI's response is spoken back to the caller
6. **Loop**: The conversation continues until the caller hangs up

## Upgrading to Premium Voice Quality

Currently, the phone integration uses Twilio's built-in TTS. To use OpenAI's premium voices:

1. Pre-generate audio files using your `/api/text-to-speech` endpoint
2. Host them on a public URL (AWS S3, Cloudflare, etc.)
3. Use Twilio's `<Play>` verb instead of `<Say>` to play the audio files

## Production Deployment

For production:

1. **Deploy Backend**: Deploy your FastAPI backend to a cloud service (AWS, Heroku, Railway, etc.)
2. **Update Webhooks**: Update Twilio webhooks to point to your production URL
3. **Use HTTPS**: Ensure your backend uses HTTPS (required by Twilio)
4. **Database**: Replace in-memory storage with a real database
5. **Media Streams**: For real-time bidirectional audio, implement WebSocket support

## Troubleshooting

### "Twilio credentials not found"
- Check that your `.env` file has `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN`
- Make sure the `.env` file is in the `backend/` directory

### "Webhook not receiving calls"
- Verify ngrok is running and your backend is accessible
- Check Twilio webhook URLs are correct
- Look at Twilio Console → Monitor → Logs for errors

### "No audio or speech not working"
- Check Twilio phone number has Voice capability
- Verify webhook endpoints are returning valid TwiML
- Check backend logs for errors

## Next Steps

- [ ] Implement real-time Media Streams for bidirectional audio
- [ ] Add call recording functionality
- [ ] Integrate with your appointment/message system
- [ ] Add analytics and call logging
- [ ] Support multiple languages

## Support

For issues:
- Check Twilio [Documentation](https://www.twilio.com/docs)
- Review backend logs
- Check Twilio Console → Monitor → Logs


