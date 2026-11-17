"""Load a firm's config (rules + price list) into DynamoDB.

Usage:
    python scripts/seed_firm.py seed/demo_firm.json <FirmsTableName>
"""
import json
import sys
from decimal import Decimal

import boto3


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    path, table_name = sys.argv[1], sys.argv[2]

    with open(path) as f:
        firm = json.load(f, parse_float=Decimal)  # DynamoDB needs Decimal, not float

    if "REPLACE_WITH" in firm["partner_email"]:
        sys.exit("Edit partner_email in the JSON file first.")

    # Uses the region from `aws configure` (your account's home region).
    boto3.resource("dynamodb").Table(table_name).put_item(Item=firm)
    print(f"Saved firm '{firm['firm_id']}' to {table_name}")


if __name__ == "__main__":
    main()
