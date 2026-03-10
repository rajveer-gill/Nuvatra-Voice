# Voice preview samples

Pre-recorded MP3s for the dashboard voice settings preview. These are played when users click the play button next to each voice so there is no delay.

## Regenerating

When you change the sample text or add a voice:

1. Set `OPENAI_API_KEY` in `backend/.env`.
2. From the **project root**:
   ```bash
   python backend/scripts/generate_voice_samples.py
   ```
3. Commit the updated `*.mp3` files in this directory.

Sample text is defined in `backend/voice_preview.py` (`VOICE_PREVIEW_SAMPLE_TEXT`). The script uses the same TTS pipeline as production (tts-1-hd, speed 1.0, sentence pauses).
