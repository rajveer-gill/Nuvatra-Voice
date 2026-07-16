"""The false-verbal-confirm guard must catch a claimed booking with no BOOKING: line.

This guard only runs when the model did NOT emit a BOOKING: line, so ANY claim that an
appointment exists or that a confirmation text is coming is a false promise by definition —
the caller hangs up believing they're booked and nothing was created.

Regression: these exact phrasings slipped past the guard on a live customer demo. The caller
was never asked for their name, so no booking could be created, yet the AI said it had
everything and that a text was coming. Nothing existed; the caller had no idea.
"""
import pytest

from conversation_service import _ai_implies_committed_booking

# Verbatim from the failed prod demo call (CA714d7f8e) — the one that must never slip again.
DEMO_FAILURE = (
    "Perfect, I've got everything I need. We'll send a text to confirm your appointment "
    "for a long cut with Andrew on Tuesday, July 21st, at 2 PM. Thank you!"
)
# Verbatim from an earlier prod call that DID trip the guard ("got you down") — keep it caught.
EARLIER_FAILURE = (
    "Great, Alex! I've got you down for a long cut with Jake on Friday, July 17th at 2 PM. "
    "We'll send a text to confirm. Anything else you'd like to add?"
)


@pytest.mark.parametrize(
    "reply",
    [
        DEMO_FAILURE,
        EARLIER_FAILURE,
        "You're all set for Friday at 2!",
        "Consider it booked.",
        "I've put you down for Tuesday at 2 PM.",
        "You're set for Friday at 2 PM.",
        "Great — see you then!",
    ],
)
def test_catches_claimed_bookings(reply):
    assert _ai_implies_committed_booking(reply) is True


@pytest.mark.parametrize(
    "reply",
    [
        # PARAPHRASES the model has never actually said — the guard must generalize, not
        # memorize. A literal blocklist is what let the demo failure through.
        "Awesome, we have everything we need — talk soon!",
        "That's all I need, thanks!",
        "I have scheduled you for Tuesday at 2 PM.",
        "We've booked you in with Andrew.",
        "I have got you down for a long cut.",
        "We'll put you in for Friday.",
        "Your appointment is set for Tuesday.",
        "Your booking has been confirmed.",
        "Let me confirm your appointment for Tuesday at 2.",
        "You are booked with Jake.",
        "Consider it scheduled!",
    ],
)
def test_generalizes_to_unseen_paraphrases(reply):
    assert _ai_implies_committed_booking(reply) is True


@pytest.mark.parametrize(
    "reply",
    [
        # Legitimate mid-booking replies: gathering details, promising nothing yet. The prompt
        # explicitly tells the model to say it will text to confirm WHILE still collecting, so
        # these must NOT be rewritten or the normal flow breaks.
        "Sure! What service would you like — a short cut or a long cut?",
        "Could I have your name, please?",
        "Jake works Monday, Wednesday, and Friday. Which day would you like?",
        "I'm gathering your details and will text you to confirm.",
        "What day and time works best for you?",
        "",
    ],
)
def test_does_not_flag_normal_gathering_replies(reply):
    assert _ai_implies_committed_booking(reply) is False
