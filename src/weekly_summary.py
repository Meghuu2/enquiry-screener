"""Lambda handler run every Monday morning by EventBridge.

Emails each firm's partner a summary of the past 7 days of enquiries.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone

import aws_io


def build_summary(firm: dict, enquiries: list[dict]) -> str:
    counts = Counter(e["decision"] for e in enquiries)
    lines = [
        f"Weekly enquiry summary for {firm['firm_name']}",
        "",
        f"Total enquiries: {len(enquiries)}",
        f"  Good fits:                    {counts.get('accept', 0)}",
        f"  Needs your review:            {counts.get('review', 0)}",
        f"  Declined:                     {counts.get('decline', 0)}",
    ]

    unsent = [e for e in enquiries if e.get("status") == "awaiting_approval"]
    lines.append(f"  Replies still waiting for your approval: {len(unsent)}")

    accepted = [e for e in enquiries if e["decision"] == "accept"]
    if accepted:
        low = sum(e["estimate_low"] for e in accepted)
        high = sum(e["estimate_high"] for e in accepted)
        lines += ["", f"Potential annual fees from accepted enquiries: £{low:,} to £{high:,}"]

    by_type = Counter(e["enquiry"]["business_type"] for e in enquiries)
    if by_type:
        lines += ["", "By business type:"]
        lines += [f"  {t.replace('_', ' ')}: {n}" for t, n in by_type.most_common()]

    pending = [e for e in enquiries if e["decision"] == "review"]
    if pending:
        lines += ["", "Still to review:"]
        lines += [f"  {e['enquiry']['name']} <{e['enquiry']['email']}> score {e['score']}" for e in pending]

    return "\n".join(lines)


def handler(event, context):
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    for firm in aws_io.list_firms():
        enquiries = aws_io.enquiries_since(firm["firm_id"], since)
        aws_io.send_email(
            firm["partner_email"],
            f"Weekly enquiry summary: {len(enquiries)} new",
            build_summary(firm, enquiries),
        )
    return {"ok": True}
