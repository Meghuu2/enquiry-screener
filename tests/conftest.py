import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture
def firm():
    with open(ROOT / "seed" / "demo_firm.json") as f:
        data = json.load(f)
    data["partner_email"] = "partner@example.com"
    return data


@pytest.fixture
def good_raw():
    """A strong-fit enquiry: limited company, on Xero, organised, wants bookkeeping."""
    return {
        "firm_id": "demo-firm",
        "name": "Priya Shah",
        "email": "priya@example.com",
        "phone": "",
        "business_type": "limited_company",
        "turnover": 180000,
        "services": ["annual_accounts", "bookkeeping", "vat_returns"],
        "software": "xero",
        "records_state": "organised",
        "deadline": None,
        "message": "Looking to switch accountants before our year end.",
        "consent": True,
        "website": "",
    }


@pytest.fixture
def poor_raw(good_raw):
    """A poor-fit enquiry: tiny sole trader, paper records, messy."""
    return {
        **good_raw,
        "business_type": "sole_trader",
        "turnover": 15000,
        "services": ["self_assessment"],
        "software": "paper",
        "records_state": "messy",
    }


class FakeBedrock:
    """Pretends to be the Bedrock client and returns a canned JSON reply."""

    def __init__(self, flags=None, fail=False):
        self.flags = flags or []
        self.fail = fail
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("Bedrock is down")
        payload = json.loads(kwargs["messages"][0]["content"][0]["text"])
        reply = {
            "flags": self.flags,
            "partner_note": "Test note.",
            "reply_subject": f"Re: enquiry ({payload['decision']})",
            "reply_body": f"Draft for {payload['decision']}",
        }
        return {"output": {"message": {"content": [{"text": json.dumps(reply)}]}}}


@pytest.fixture
def make_deps(firm):
    def _make(bedrock=None):
        sent, saved = [], []

        def save(fid, rec):
            saved.append(rec)
            return f"2026-11-12T10:00:00#{len(saved)}"

        deps = {
            "get_firm": lambda fid: firm if fid == firm["firm_id"] else None,
            "save_enquiry": save,
            "approve_base_url": "https://api.example.com/approve",
            "send_email": lambda to, subject, body, reply_to=None: sent.append(
                {"to": to, "subject": subject, "body": body}),
            "bedrock_client": bedrock,
            "model_id": "test-model" if bedrock else None,
        }
        return deps, sent, saved
    return _make
