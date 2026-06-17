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
    # Extra details the receptionist should gather at booking, specific to this
    # industry (injected into the voice prompt). Empty = no industry-specific
    # intake beyond the generic name/date/time/service flow.
    intake_guidance: str = ""
    # Example service names shown as hints in the dashboard service editor.
    service_examples: str = ""
    # Structured details captured on the call and shown on the appointment, as
    # (key, label) pairs. Empty for verticals with no structured intake. Kept as a
    # tuple of tuples so VerticalTerms stays hashable (frozen dataclass).
    intake_fields: tuple = ()


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
        intake_guidance="",
        service_examples="Short Cut, Long Cut, Color, Blowout",
        intake_fields=(),
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
        # Auto body intake is different from a salon's: the shop needs the vehicle,
        # how the job is paid for, what's wrong, and whether the car can be driven
        # in. The AI gathers these conversationally and summarizes them in the
        # booking reason so the shop sees them on the confirmation.
        intake_guidance=(
            "AUTO BODY INTAKE: This is an auto body / collision shop. Most callers want an estimate, "
            "a drop-off, or a status update on a repair. When booking an estimate or drop-off, naturally "
            "gather (don't interrogate—ask as it flows): (1) the VEHICLE: year, make, and model; "
            "(2) whether it's an INSURANCE claim or out-of-pocket, and the insurer if they mention it; "
            "(3) a short description of the DAMAGE or work needed (e.g. rear bumper, hail dents, scratch, "
            "collision); (4) whether the car is DRIVABLE (if not, mention they may need a tow). "
            "Summarize these in the booking reason field, e.g. "
            "\"Collision estimate — 2019 Honda Civic, Geico claim, rear bumper, drivable\". "
            "If the caller asks whether you take their insurance, say the shop works with most major "
            "insurers and can confirm their specific one—do not invent a list. Don't block the booking "
            "if they don't know every detail; capture what they have."
        ),
        service_examples="Collision Estimate, Dent Repair, Bumper Repair, Paint, Glass Replacement",
        intake_fields=(
            ("vehicle", "Vehicle"),
            ("insurance", "Insurance"),
            ("damage", "Damage / work needed"),
            ("drivable", "Drivable"),
        ),
    ),
}


def intake_field_dicts(key: object) -> List[Dict[str, str]]:
    """[{key,label}] of a vertical's structured intake fields (for the API/UI)."""
    return [{"key": k, "label": label} for k, label in terms_for(key).intake_fields]


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
