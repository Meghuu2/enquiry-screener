import pytest

from approve import send_approved, show_draft

TOKEN = "s3cret-token-abcdefghijklmnopqrstuvwxyz"


@pytest.fixture
def store(firm):
    """A fake enquiries table holding one draft, plus a record of sent emails."""
    record = {
        "enquiry": {"name": "Priya Shah", "email": "priya@example.com"},
        "decision": "accept", "score": 90, "reasons": ["+20: Limited company"], "flags": [],
        "estimate_low": 2820, "estimate_high": 3810,
        "draft_subject": "Your enquiry", "draft_body": "Hi Priya, <script>alert(1)</script>",
        "status": "awaiting_approval", "approval_token": TOKEN,
    }
    sent = []

    def claim(f, c, subject, body):
        if record["status"] != "awaiting_approval":
            return False
        record["status"] = "sent"
        return True

    def release(f, c):
        record["status"] = "awaiting_approval"

    deps = {
        "get_enquiry": lambda f, c: record if (f, c) == ("demo-firm", "key1") else None,
        "get_firm": lambda f: firm,
        "claim_for_sending": claim,
        "release_claim": release,
        "send_email": lambda to, s, b, reply_to=None: sent.append((to, s, b)),
    }
    return record, sent, deps


GOOD = {"f": "demo-firm", "c": "key1", "t": TOKEN}


def test_valid_link_shows_editable_draft(store):
    _, sent, deps = store
    page = show_draft(GOOD, deps)
    assert page["statusCode"] == 200
    assert "<textarea" in page["body"]
    assert sent == []  # opening the link never sends (protects against link scanners)


def test_draft_is_html_escaped(store):
    _, _, deps = store
    body = show_draft(GOOD, deps)["body"]
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


def test_wrong_token_rejected(store):
    _, sent, deps = store
    assert show_draft({**GOOD, "t": "wrong"}, deps)["statusCode"] == 404
    assert send_approved({**GOOD, "t": "wrong"}, deps)["statusCode"] == 404
    assert sent == []


def test_send_uses_edited_text_and_only_once(store):
    record, sent, deps = store
    page = send_approved({**GOOD, "subject": "Edited subject", "body": "Edited body"}, deps)
    assert "Sent" in page["body"]
    assert sent == [("priya@example.com", "Edited subject", "Edited body")]

    again = send_approved(GOOD, deps)  # double click
    assert "Already sent" in again["body"]
    assert len(sent) == 1


def test_failed_send_can_be_retried(store):
    record, sent, deps = store

    def boom(*a, **k):
        raise RuntimeError("SES down")

    deps["send_email"] = boom
    assert send_approved(GOOD, deps)["statusCode"] == 502
    assert record["status"] == "awaiting_approval"  # claim released for retry
