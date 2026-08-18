"""The end-of-call reconciler's gate, which decides whether a call is even looked at.

A false negative here is the worst failure the voice path has: the caller was told
"I've sent your request to the salon", nothing was written, and the safety net that
exists to catch exactly that never ran.

It happened. A caller asked for bright blue hair and booked a Vivid color for
Thursday at 1 PM — service, day, time, stylist and name all agreed — and every one
of their turns was "Yeah", "Thursday afternoon", "That's fine", "Anyone's fine",
"Raj". The gate matched booking keywords against the CALLER only, and the caller
never used one, because the AI supplied all the booking vocabulary.
"""

from __future__ import annotations

import pytest

import conversation_service as cs


def _turns(*pairs):
    return [{"role": r, "content": c} for r, c in pairs]


# --- The call that was lost ---------------------------------------------------

_VIVID_CALL = _turns(
    ("user", "Hi. I wanna dye my hair bright blue."),
    ("assistant", "We can help with that by booking a Vivid color service. Would you like to schedule an appointment?"),
    ("user", "Yeah."),
    ("assistant", "Great! Which day and time would you like to request for your Vivid color appointment?"),
    ("user", "Thursday afternoon."),
    ("assistant", "Could you please specify a time on Thursday? How about around 1 PM?"),
    ("user", "That's fine."),
    ("assistant", "Which stylist would you prefer for your Vivid color appointment?"),
    ("user", "Anyone's fine."),
    ("assistant", "I'll put in a request for Thursday at 1 PM. What's your name, please?"),
    ("user", "Raj."),
)


def test_the_caller_never_says_book_and_it_still_counts():
    assert cs._conversation_suggests_booking(_VIVID_CALL) is True


def test_no_user_turn_in_that_call_contains_a_keyword():
    """The premise. If this ever fails the fix above is being tested vacuously."""
    assert not any(
        cs._suggests_booking(m["content"]) for m in _VIVID_CALL if m["role"] == "user"
    )


# --- Still true for the cases that already worked -----------------------------


@pytest.mark.parametrize(
    "said",
    ["I'd like to book a haircut", "do you have an appointment tomorrow",
     "can I schedule something", "what times are available"],
)
def test_a_caller_who_says_it_outright_still_counts(said):
    assert cs._conversation_suggests_booking(_turns(("user", said))) is True


# --- And false for calls that genuinely aren't bookings -----------------------


def test_a_question_about_hours_is_not_a_booking():
    assert cs._conversation_suggests_booking(
        _turns(
            ("user", "What time do you close?"),
            ("assistant", "We're open until 5. Would you like to book an appointment?"),
        )
    ) is False


def test_a_single_engaged_turn_is_not_enough():
    """One reply to an offer shouldn't drag every call into the extractor."""
    assert cs._conversation_suggests_booking(
        _turns(
            ("user", "Where are you located?"),
            ("assistant", "We're on Main Street. Can I take your name and book you in?"),
        )
    ) is False


def test_a_generic_offer_to_book_is_not_taking_details():
    """The AI offers to book on nearly every call; that alone must not count, or the
    gate is just 'always true' wearing a disguise."""
    assert cs._conversation_suggests_booking(
        _turns(
            ("user", "Do you do beard trims?"),
            ("assistant", "We do. Would you like to book an appointment at Test Store?"),
            ("user", "No thanks, just asking."),
            ("assistant", "No problem at all. Have a great day!"),
        )
    ) is False


def test_an_empty_conversation_is_not_a_booking():
    assert cs._conversation_suggests_booking([]) is False
    assert cs._conversation_suggests_booking(None) is False
