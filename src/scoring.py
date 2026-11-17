"""Scores an enquiry against one firm's own client-fit rules.

The decision is made by plain, auditable rules, not by the AI. A partner can
read every rule and see exactly why an enquiry was accepted or declined.
"""

START_SCORE = 50


def _rule_matches(rule: dict, enquiry: dict) -> bool:
    field, op, target = rule["field"], rule["op"], rule.get("value")
    actual = enquiry.get(field)

    if op == "eq":
        return actual == target
    if op == "in":
        return actual in target
    if op == "gte":
        return actual is not None and actual >= target
    if op == "lte":
        return actual is not None and actual <= target
    if op == "contains_any":
        return isinstance(actual, list) and any(item in actual for item in target)
    raise ValueError(f"Unknown rule operator: {op}")


def score_enquiry(enquiry: dict, firm: dict, ai_flags: list[str] | None = None) -> dict:
    """Return score, decision ('accept', 'review' or 'decline') and reasons."""
    score = START_SCORE
    reasons = []

    for rule in firm["rules"]:
        if _rule_matches(rule, enquiry):
            points = int(rule["points"])
            score += points
            reasons.append(f"{'+' if points >= 0 else ''}{points}: {rule['reason']}")

    score = max(0, min(100, score))

    if score >= firm["accept_threshold"]:
        decision = "accept"
    elif score < firm["review_threshold"]:
        decision = "decline"
    else:
        decision = "review"

    # The AI may only make things MORE cautious. A red flag in the free-text
    # message can move "accept" down to "review", never the other way round.
    if ai_flags and decision == "accept":
        decision = "review"
        reasons.append("Moved to review: possible issues in the message (" + "; ".join(ai_flags) + ")")

    return {"score": score, "decision": decision, "reasons": reasons}
