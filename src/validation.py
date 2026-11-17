"""Checks and cleans a raw enquiry from the website form.

Everything that arrives from the public internet is untrusted, so this module
is the only place that decides what a "valid enquiry" looks like. Every other
module can then assume the data is clean.
"""
import re
from datetime import date

BUSINESS_TYPES = {"sole_trader", "landlord", "limited_company", "partnership", "individual"}
SERVICES = {
    "self_assessment", "annual_accounts", "bookkeeping", "vat_returns",
    "payroll", "mtd_quarterly", "advisory",
}
SOFTWARE = {"xero", "quickbooks", "freeagent", "sage", "spreadsheets", "paper", "none", "other"}
RECORDS_STATES = {"organised", "mostly", "messy"}

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[a-zA-Z]{2,}$")
MAX_MESSAGE_CHARS = 2000
MAX_TURNOVER = 100_000_000


class ValidationError(ValueError):
    """Raised with a short, user-safe message when the form data is invalid."""


def _clean_text(value, field, max_len, required=True):
    if value is None or str(value).strip() == "":
        if required:
            raise ValidationError(f"{field} is required")
        return ""
    text = str(value).strip()
    if len(text) > max_len:
        raise ValidationError(f"{field} is too long")
    return text


def validate_enquiry(raw: dict, today: date | None = None) -> dict:
    """Return a clean enquiry dict, or raise ValidationError."""
    if not isinstance(raw, dict):
        raise ValidationError("Invalid request")

    # Honeypot: a hidden field real people never fill in. Bots usually do.
    if str(raw.get("website", "")).strip():
        raise ValidationError("spam")

    if raw.get("consent") is not True:
        raise ValidationError("Consent to process your details is required")

    name = _clean_text(raw.get("name"), "name", 100)
    email = _clean_text(raw.get("email"), "email", 254).lower()
    if not EMAIL_RE.match(email):
        raise ValidationError("email is not valid")
    phone = _clean_text(raw.get("phone"), "phone", 30, required=False)

    business_type = raw.get("business_type")
    if business_type not in BUSINESS_TYPES:
        raise ValidationError("business_type is not valid")

    try:
        turnover = int(raw.get("turnover"))
    except (TypeError, ValueError):
        raise ValidationError("turnover must be a whole number")
    if not 0 <= turnover <= MAX_TURNOVER:
        raise ValidationError("turnover is out of range")

    services = raw.get("services")
    if not isinstance(services, list) or not services:
        raise ValidationError("choose at least one service")
    services = sorted({s for s in services if s in SERVICES})
    if not services:
        raise ValidationError("services are not valid")

    software = raw.get("software")
    if software not in SOFTWARE:
        raise ValidationError("software is not valid")

    records_state = raw.get("records_state")
    if records_state not in RECORDS_STATES:
        raise ValidationError("records_state is not valid")

    deadline = None
    if raw.get("deadline"):
        try:
            deadline = date.fromisoformat(str(raw["deadline"]))
        except ValueError:
            raise ValidationError("deadline must be a date like 2027-01-31")

    message = _clean_text(raw.get("message"), "message", MAX_MESSAGE_CHARS, required=False)

    today = today or date.today()
    days_to_deadline = (deadline - today).days if deadline else None

    return {
        "name": name,
        "email": email,
        "phone": phone,
        "business_type": business_type,
        "turnover": turnover,
        "services": services,
        "software": software,
        "records_state": records_state,
        "deadline": deadline.isoformat() if deadline else None,
        "days_to_deadline": days_to_deadline,
        "message": message,
    }
