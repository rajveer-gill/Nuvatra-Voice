"""Per-vertical terminology registry — the single source of truth for industries.

A tenant's ``business_vertical`` selects an industry; each industry maps to the
words the receptionist uses out loud and in SMS (what to call a service
provider, how to describe the business). Prompts, SMS, and booking code read
their wording from :func:`terms_for` instead of hardcoding "stylist"/"salon", so
adding a new vertical is a single entry in ``_VERTICALS`` below — no prompt
surgery elsewhere.

This module is intentionally dependency-free (pure data + helpers). It imports
nothing from the app, so it is safe to import anywhere — including
``prompts/receptionist.py``, which must stay free of DB/Twilio imports.

Back-compat: ``salon_chair`` wording is reproduced byte-for-byte from the
original hardcoded strings, so existing salon behavior (and its tests) is
unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

# Used when a tenant has no vertical set, or an unknown one is stored.
DEFAULT_VERTICAL = "salon_chair"


@dataclass(frozen=True)
class VerticalTerms:
    """The vocabulary one industry uses across prompts and customer messaging."""

    key: str
    # Human label shown in onboarding/Settings industry pickers.
    label: str
    # Service provider, singular lowercase — e.g. "stylist", "technician".
    provider: str
    # Plural lowercase — e.g. "stylists", "technicians".
    provider_plural: str
    # Capitalized, for SMS field labels — e.g. "Stylist", "Technician".
    provider_label: str
    # ALL CAPS, for prompt section headers — e.g. "STYLIST", "TECHNICIAN".
    provider_caps: str
    # How SMS-rewrite prompts describe the business to the model.
    business_phrase: str
    # Noun for the premises — e.g. "the whole salon is closed" / "the whole shop is closed".
    venue: str


_VERTICALS: Dict[str, VerticalTerms] = {
    "salon_chair": VerticalTerms(
        key="salon_chair",
        label="Salon, barbershop, nails & similar (chair services)",
        provider="stylist",
        provider_plural="stylists",
        provider_label="Stylist",
        provider_caps="STYLIST",
        business_phrase="salon, barbershop, or nail studio",
        venue="salon",
    ),
    "auto_body": VerticalTerms(
        key="auto_body",
        label="Auto body shop & collision center",
        provider="technician",
        provider_plural="technicians",
        provider_label="Technician",
        provider_caps="TECHNICIAN",
        business_phrase="auto body shop or collision center",
        venue="shop",
    ),
}


def is_supported(key: object) -> bool:
    """True when ``key`` names a registered vertical."""
    return isinstance(key, str) and key.strip() in _VERTICALS


def allowed_verticals() -> frozenset:
    """Set of valid vertical keys (drives API validation)."""
    return frozenset(_VERTICALS.keys())


def vertical_labels() -> Dict[str, str]:
    """Map of vertical key -> human label."""
    return {k: v.label for k, v in _VERTICALS.items()}


def terms_for(key: object) -> VerticalTerms:
    """Terminology for a vertical, falling back to the default when unknown.

    Accepts the raw stored value (may be None/blank/unknown) and always returns
    a usable :class:`VerticalTerms`, so callers never have to guard.
    """
    if isinstance(key, str):
        hit = _VERTICALS.get(key.strip())
        if hit:
            return hit
    return _VERTICALS[DEFAULT_VERTICAL]


def vertical_choices() -> List[Dict[str, str]]:
    """[{value, label}] for frontend industry pickers, in registry order."""
    return [{"value": k, "label": v.label} for k, v in _VERTICALS.items()]
