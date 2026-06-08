"""The Twilio media trust boundary: credentials are only ever attached to
https URLs on a Twilio-owned host. A forged RecordingUrl in a webhook body
must never cause a server-side fetch (SSRF) or credential exfiltration."""

from __future__ import annotations

import main


def test_accepts_twilio_https_hosts():
    assert main._is_trusted_twilio_media_url(
        "https://api.twilio.com/2010-04-01/Accounts/AC/Recordings/RE123"
    )
    assert main._is_trusted_twilio_media_url(
        "https://api.us1.twilio.com/2010-04-01/Accounts/AC/Recordings/RE123"
    )


def test_rejects_ssrf_and_spoofed_hosts():
    bad = [
        "http://api.twilio.com/x",  # not https
        "https://169.254.169.254/latest/meta-data/",  # cloud metadata SSRF
        "http://169.254.169.254/",
        "https://attacker.com/x",
        "https://api.twilio.com.attacker.com/x",  # suffix spoof
        "https://twilio.com.evil.com/x",
        "https://localhost/x",
        "",
        None,  # type: ignore[arg-type]
        "not-a-url",
        "ftp://api.twilio.com/x",
    ]
    for url in bad:
        assert not main._is_trusted_twilio_media_url(url), url


def test_fetch_helper_refuses_untrusted_without_calling_httpx():
    # 0/empty sentinel means "did not fetch" — no credentials left the process.
    code, content = main._fetch_twilio_recording_bytes("https://attacker.com/evil.mp3")
    assert code == 0
    assert content == b""
