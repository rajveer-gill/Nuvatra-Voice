#!/bin/bash
echo "Starting ngrok to expose backend on port 8000..."
echo ""
echo "Make sure your backend is running on port 8000 first!"
echo ""
echo "After ngrok starts, copy the HTTPS URL (e.g., https://abc123.ngrok.io)"
echo "and use it in your Twilio webhook configuration."
echo ""
ngrok http 8000


