#!/usr/bin/env python3
"""
Generate pre-recorded voice sample MP3s for the dashboard voice preview.
Uses the same TTS pipeline as production (add_sentence_pauses, tts-1-hd, speed 1.0).

Run from project root:
  python backend/scripts/generate_voice_samples.py

Requires OPENAI_API_KEY in backend/.env (or environment).
Output: public/voice-samples/{voice}.mp3 for each voice.
"""
from pathlib import Path
import os
import sys

# Ensure backend is on path so we can import voice_preview
_script_dir = Path(__file__).resolve().parent
_backend_dir = _script_dir.parent
_project_root = _backend_dir.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

# Load .env from backend
from dotenv import load_dotenv
load_dotenv(_backend_dir / ".env", override=True)

import openai
from voice_preview import VOICE_PREVIEW_SAMPLE_TEXT, TTS_VOICES, add_sentence_pauses


def main() -> None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set. Set it in backend/.env or the environment.")
        sys.exit(1)

    out_dir = _project_root / "public" / "voice-samples"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {out_dir}")
    print(f"Sample text: {VOICE_PREVIEW_SAMPLE_TEXT!r}")
    print(f"Voices: {TTS_VOICES}")

    client = openai.OpenAI(api_key=api_key)
    text_with_pauses = add_sentence_pauses(VOICE_PREVIEW_SAMPLE_TEXT)

    for voice in TTS_VOICES:
        out_path = out_dir / f"{voice}.mp3"
        print(f"Generating {voice}...", end=" ", flush=True)
        try:
            response = client.audio.speech.create(
                model="tts-1-hd",
                voice=voice,
                input=text_with_pauses,
                speed=1.0,
            )
            out_path.write_bytes(response.content)
            print(f"OK -> {out_path.name}")
        except Exception as e:
            print(f"FAILED: {e}")
            sys.exit(1)

    print("Done. Commit public/voice-samples/*.mp3 to the repo.")


if __name__ == "__main__":
    main()
