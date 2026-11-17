"""Run three sample enquiries through the system locally and print the emails.

No AWS needed: storage and email are faked, and replies use the templates.
Usage:  python scripts/local_demo.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from submit_enquiry import process_enquiry  # noqa: E402

firm = json.loads((ROOT / "seed" / "demo_firm.json").read_text())
firm["partner_email"] = "partner@demo-firm.co.uk"

base = {
    "firm_id": "demo-firm", "phone": "", "deadline": None, "consent": True, "website": "",
}
samples = [
    {**base, "name": "Priya Shah", "email": "priya@example.com", "business_type": "limited_company",
     "turnover": 180000, "services": ["annual_accounts", "bookkeeping", "vat_returns"],
     "software": "xero", "records_state": "organised", "message": "Switching before our year end."},
    {**base, "name": "Tom Reed", "email": "tom@example.com", "business_type": "landlord",
     "turnover": 45000, "services": ["self_assessment", "mtd_quarterly"],
     "software": "spreadsheets", "records_state": "mostly", "message": "Two rental flats."},
    {**base, "name": "Dan Cole", "email": "dan@example.com", "business_type": "sole_trader",
     "turnover": 15000, "services": ["self_assessment"], "software": "paper",
     "records_state": "messy", "message": "Need my return done asap."},
]

for raw in samples:
    sent = []
    deps = {
        "get_firm": lambda fid: firm,
        "save_enquiry": lambda fid, rec: "2026-11-12T10:00:00#demo",
        "approve_base_url": "https://YOUR-API.execute-api.REGION.amazonaws.com/approve",
        "send_email": lambda to, s, b, reply_to=None: sent.append((to, s, b)),
        "bedrock_client": None,
        "model_id": None,
    }
    result = process_enquiry(raw, deps)
    print("=" * 70)
    print(f"{raw['name']}: {result['decision'].upper()} (score {result['score']})")
    for to, subject, body in sent:
        print(f"\n--- To: {to}\n--- Subject: {subject}\n{body}")
    print()
