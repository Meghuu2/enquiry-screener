from datetime import date

import pytest

from conftest import FakeBedrock
from pricing import estimate_fee
from scoring import score_enquiry
from submit_enquiry import handler, process_enquiry
from validation import ValidationError, validate_enquiry
from weekly_summary import build_summary


# ---------- validation ----------

def test_valid_enquiry_is_cleaned(good_raw):
    e = validate_enquiry({**good_raw, "email": "  Priya@Example.com "})
    assert e["email"] == "priya@example.com"
    assert e["services"] == ["annual_accounts", "bookkeeping", "vat_returns"]


@pytest.mark.parametrize("field,value", [
    ("email", "not-an-email"),
    ("business_type", "spaceship"),
    ("turnover", "lots"),
    ("services", []),
    ("consent", False),
    ("message", "x" * 2001),
])
def test_bad_input_is_rejected(good_raw, field, value):
    with pytest.raises(ValidationError):
        validate_enquiry({**good_raw, field: value})


def test_honeypot_flags_spam(good_raw):
    with pytest.raises(ValidationError, match="spam"):
        validate_enquiry({**good_raw, "website": "http://spam.example"})


def test_days_to_deadline(good_raw):
    e = validate_enquiry({**good_raw, "deadline": "2027-01-31"}, today=date(2027, 1, 21))
    assert e["days_to_deadline"] == 10


# ---------- scoring ----------

def test_good_fit_is_accepted(good_raw, firm):
    result = score_enquiry(validate_enquiry(good_raw), firm)
    assert result["decision"] == "accept"
    assert result["reasons"]


def test_poor_fit_is_declined(poor_raw, firm):
    assert score_enquiry(validate_enquiry(poor_raw), firm)["decision"] == "decline"


def test_ai_flags_can_only_downgrade(good_raw, poor_raw, firm):
    good = score_enquiry(validate_enquiry(good_raw), firm, ai_flags=["HMRC investigation"])
    assert good["decision"] == "review"
    poor = score_enquiry(validate_enquiry(poor_raw), firm, ai_flags=["anything"])
    assert poor["decision"] == "decline"  # flags never upgrade


# ---------- pricing ----------

def test_fee_estimate(good_raw, firm):
    est = estimate_fee(validate_enquiry(good_raw), firm)
    # base 1200 + bookkeeping 900 + VAT 450 = 2550, x1.3 turnover band = 3315
    assert est["multiplier"] == 1.3
    assert est["low"] == 2820 and est["high"] == 3810


def test_rush_surcharge(good_raw, firm):
    e = validate_enquiry({**good_raw, "deadline": "2027-01-31"}, today=date(2027, 1, 21))
    items = [line["item"] for line in estimate_fee(e, firm)["breakdown"]]
    assert "Short-deadline surcharge" in items


# ---------- full flow ----------

@pytest.mark.parametrize("raw_name", ["good_raw", "poor_raw"])
def test_nothing_ever_auto_sent_to_prospect(raw_name, request, make_deps):
    deps, sent, saved = make_deps(FakeBedrock())
    process_enquiry(request.getfixturevalue(raw_name), deps)
    assert [m["to"] for m in sent] == ["partner@example.com"]  # partner only
    assert saved[0]["status"] == "awaiting_approval"
    assert "Nothing has been sent" in sent[0]["body"]


def test_partner_email_has_approval_link(good_raw, make_deps):
    deps, sent, saved = make_deps(FakeBedrock())
    process_enquiry(good_raw, deps)
    token = saved[0]["approval_token"]
    assert len(token) >= 30
    assert f"t={token}" in sent[0]["body"]
    assert "https://api.example.com/approve?f=demo-firm" in sent[0]["body"]


def test_red_flag_downgrades_and_redrafts(good_raw, make_deps):
    bedrock = FakeBedrock(flags=["Under HMRC investigation"])
    deps, sent, saved = make_deps(bedrock)
    result = process_enquiry(good_raw, deps)
    assert result["decision"] == "review"
    assert len(bedrock.calls) == 2  # redrafted for the new decision
    assert saved[0]["draft_subject"] == "Re: enquiry (review)"  # no fee quoted
    assert saved[0]["flags"] == ["Under HMRC investigation"]


def test_bedrock_failure_falls_back_to_template(good_raw, make_deps):
    deps, sent, saved = make_deps(FakeBedrock(fail=True))
    process_enquiry(good_raw, deps)
    assert "£2,820 to £3,810" in saved[0]["draft_body"]
    assert "Template reply used" in sent[0]["body"]


def test_no_ai_configured_still_works(good_raw, make_deps):
    deps, sent, saved = make_deps(None)
    process_enquiry(good_raw, deps)
    assert len(sent) == 1 and saved[0]["draft_body"]


def test_unknown_firm_rejected(good_raw, make_deps):
    deps, _, _ = make_deps(None)
    with pytest.raises(ValidationError):
        process_enquiry({**good_raw, "firm_id": "nope"}, deps)


def test_handler_bad_json_returns_400():
    assert handler({"body": "{not json"}, None)["statusCode"] == 400


# ---------- weekly summary ----------

def test_weekly_summary(firm):
    records = [
        {"decision": "accept", "estimate_low": 1000, "estimate_high": 1400, "score": 80,
         "enquiry": {"business_type": "limited_company", "name": "A", "email": "a@x.com"}},
        {"decision": "review", "estimate_low": 500, "estimate_high": 700, "score": 50,
         "enquiry": {"business_type": "sole_trader", "name": "B", "email": "b@x.com"}},
    ]
    text = build_summary(firm, records)
    assert "Total enquiries: 2" in text
    assert "£1,000 to £1,400" in text
    assert "B <b@x.com> score 50" in text
