"""Linking a pasted stylist name to someone on the roster.

Without this every imported appointment landed with staff_id NULL, so a day that
actually had four stylists working read as one column of fifteen overlapping slivers.
The name was only ever written into the reason text, where nothing could group by it.

Matching has to be forgiving — the other system carries names as its operators typed
them, "BRENDA TO" and "Dai  Dao" — and refuse to guess, because putting a customer in
front of the wrong stylist is worse than leaving the row unassigned.
"""

from __future__ import annotations

import pytest

from routers.appointments import _staff_id_by_name

_ROSTER = [
    {"id": "s-tina", "name": "Tina Nguyen"},
    {"id": "s-brenda", "name": "BRENDA TO"},
    {"id": "s-dai", "name": "Dai Dao"},
    {"id": "s-rin", "name": "Rin Chan"},
]


@pytest.mark.parametrize(
    "pasted,expected",
    [
        ("BRENDA TO", "s-brenda"),
        ("brenda to", "s-brenda"),        # the queue shouts; the roster may not
        ("  Dai  Dao ", "s-dai"),          # doubled spaces survive a copy/paste
        ("Rin Chan", "s-rin"),
        ("Tina", "s-tina"),                # first name, unambiguous here
        ("Brenda", "s-brenda"),
    ],
)
def test_a_name_from_the_queue_finds_its_stylist(pasted, expected):
    assert _staff_id_by_name(pasted, _ROSTER) == expected


@pytest.mark.parametrize("pasted", ["", "   ", "First Available", "Somebody Else", None])
def test_an_unknown_name_is_left_unassigned(pasted):
    """"First Available" is a real value in that column and names nobody."""
    assert _staff_id_by_name(pasted, _ROSTER) is None


def test_an_ambiguous_first_name_is_refused():
    """Two Tinas means "Tina" identifies no one. Guessing books a customer with the
    wrong stylist, which is worse than showing the row as unassigned."""
    roster = _ROSTER + [{"id": "s-tina2", "name": "Tina Marks"}]
    assert _staff_id_by_name("Tina", roster) is None
    # The full name still resolves.
    assert _staff_id_by_name("Tina Marks", roster) == "s-tina2"


def test_an_empty_roster_matches_nothing():
    assert _staff_id_by_name("Tina", []) is None
    assert _staff_id_by_name("Tina", None) is None


def test_rows_without_an_id_or_name_are_ignored():
    """A half-filled roster row must not swallow a match."""
    roster = [{"id": "", "name": "Tina"}, {"id": "x", "name": ""}, {"id": "ok", "name": "Tina"}]
    assert _staff_id_by_name("Tina", roster) == "ok"
