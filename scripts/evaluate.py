"""Measure how often the rules agree with an accountant's own judgement.

Your friend fills in eval/test_enquiries.csv: one row per realistic prospect,
with the decision THEY would make in the 'expected' column
(accept, review or decline). This script runs every row through the same
validation and scoring code the live system uses, then reports agreement.

Usage:
    python scripts/evaluate.py                         # uses eval/test_enquiries.csv
    python scripts/evaluate.py path/to/other.csv
"""
import csv
import json
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scoring import score_enquiry  # noqa: E402
from validation import ValidationError, validate_enquiry  # noqa: E402

DECISIONS = ["accept", "review", "decline"]


def row_to_raw(row: dict) -> dict:
    """Turn one spreadsheet row into the same shape the website form sends."""
    days = row.get("days_to_deadline", "").strip()
    deadline = (date.today() + timedelta(days=int(days))).isoformat() if days else None
    return {
        "name": row["name"],
        "email": "test@example.com",  # not needed for scoring, but validation requires one
        "business_type": row["business_type"].strip(),
        "turnover": row["turnover"].strip(),
        # Services are separated by semicolons in one cell, e.g. "bookkeeping;payroll"
        "services": [s.strip() for s in row["services"].split(";") if s.strip()],
        "software": row["software"].strip(),
        "records_state": row["records_state"].strip(),
        "deadline": deadline,
        "message": row.get("message", ""),
        "consent": True,
    }


def main():
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "eval" / "test_enquiries.csv"
    firm = json.loads((ROOT / "seed" / "demo_firm.json").read_text())

    matrix = Counter()  # (expected, predicted) -> count
    mismatches, errors = [], []

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for line_no, row in enumerate(csv.DictReader(f), start=2):
            expected = row["expected"].strip().lower()
            if expected not in DECISIONS:
                errors.append(f"Row {line_no} ({row['name']}): expected must be accept, review or decline")
                continue
            try:
                enquiry = validate_enquiry(row_to_raw(row))
            except ValidationError as exc:
                errors.append(f"Row {line_no} ({row['name']}): {exc}")
                continue

            result = score_enquiry(enquiry, firm)
            predicted = result["decision"]
            matrix[(expected, predicted)] += 1
            if predicted != expected:
                mismatches.append((row["name"], expected, predicted, result["score"], result["reasons"]))

    total = sum(matrix.values())
    if total == 0:
        sys.exit("No valid rows to evaluate.\n" + "\n".join(errors))

    agreed = sum(matrix[(d, d)] for d in DECISIONS)
    print(f"\nAgreement: {agreed}/{total} ({agreed / total:.0%})\n")

    # Confusion matrix: rows = what the accountant said, columns = what the system said.
    print(f"{'accountant \\ system':<22}" + "".join(f"{d:>10}" for d in DECISIONS))
    for exp in DECISIONS:
        print(f"{exp:<22}" + "".join(f"{matrix[(exp, pred)]:>10}" for pred in DECISIONS))

    # The most dangerous mistake: system accepts someone the accountant would decline.
    dangerous = matrix[("decline", "accept")]
    print(f"\nDangerous errors (accountant: decline, system: accept): {dangerous}")

    if mismatches:
        print("\nDisagreements:")
        for name, exp, pred, score, reasons in mismatches:
            print(f"\n  {name}: accountant said {exp}, system said {pred} (score {score})")
            for r in reasons or ["no rules matched"]:
                print(f"    {r}")

    if errors:
        print("\nRows skipped:")
        for e in errors:
            print(f"  {e}")


if __name__ == "__main__":
    main()
