"""Builds an instant fee estimate from one firm's price list.

Prices come only from the firm's own config. The AI never invents a number.
"""


def _round_to(value: float, step: int = 10) -> int:
    return int(round(value / step) * step)


def estimate_fee(enquiry: dict, firm: dict) -> dict:
    """Return an annual fee range in pounds plus a line-by-line breakdown."""
    p = firm["pricing"]
    lines = []

    base = p["base"][enquiry["business_type"]]
    lines.append((f"Base fee ({enquiry['business_type'].replace('_', ' ')})", base))

    for service in enquiry["services"]:
        price = p["services"].get(service, 0)
        if price:
            lines.append((service.replace("_", " ").capitalize(), price))

    subtotal = sum(amount for _, amount in lines)

    # Bigger businesses mean more transactions, so scale by turnover band.
    multiplier = 1.0
    for band in p["turnover_bands"]:
        if band["max"] is None or enquiry["turnover"] <= band["max"]:
            multiplier = band["multiplier"]
            break

    # Messy records take longer to process.
    multiplier *= p["records_multiplier"][enquiry["records_state"]]
    total = subtotal * multiplier

    rush = p.get("rush_surcharge")
    days = enquiry.get("days_to_deadline")
    if rush and days is not None and days <= rush["days_under"]:
        total += rush["amount"]
        lines.append(("Short-deadline surcharge", rush["amount"]))

    spread = p.get("range_pct", 0.15)
    return {
        "low": _round_to(total * (1 - spread)),
        "high": _round_to(total * (1 + spread)),
        "multiplier": round(multiplier, 2),
        "breakdown": [{"item": item, "amount": amount} for item, amount in lines],
    }
