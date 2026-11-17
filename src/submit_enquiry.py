"""Lambda handler: POST /enquiry

Flow: validate -> load firm rules -> score -> estimate fee -> AI flags and
draft -> save the draft -> email the partner with an approval link.
Nothing is sent to the prospect until the partner approves it (approve.py).
"""
import json
import os
import secrets
from urllib.parse import urlencode

import boto3

import aws_io
from ai import draft_reply
from pricing import estimate_fee
from scoring import score_enquiry
from validation import ValidationError, validate_enquiry

_bedrock = None


def _bedrock_client():
    global _bedrock
    if _bedrock is None and os.environ.get("BEDROCK_MODEL_ID"):
        _bedrock = boto3.client("bedrock-runtime")
    return _bedrock


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _partner_email(enquiry, result, estimate, draft, approve_url: str) -> str:
    reason_lines = [f"  {r}" for r in result["reasons"]] or ["  No rules matched."]
    lines = [
        f"New enquiry: {enquiry['name']} <{enquiry['email']}> {enquiry['phone']}".rstrip(),
        f"Decision: {result['decision'].upper()}  (score {result['score']}/100)",
        "",
        draft["partner_note"],
        "",
        "Why:",
        *reason_lines,
        "",
        f"Business type: {enquiry['business_type']}",
        f"Turnover: £{enquiry['turnover']:,}",
        f"Services: {', '.join(enquiry['services'])}",
        f"Software: {enquiry['software']}   Records: {enquiry['records_state']}",
        f"Deadline: {enquiry['deadline'] or 'none given'}",
        f"Fee estimate: £{estimate['low']:,} to £{estimate['high']:,}",
        "",
        "Their message:",
        enquiry["message"] or "(none)",
        "",
        "-" * 40,
        "Nothing has been sent to the prospect yet.",
        "To review, edit and send the reply below, open:",
        approve_url,
        "",
        "Draft reply:",
        "",
        f"Subject: {draft['reply_subject']}",
        "",
        draft["reply_body"],
    ]
    if draft.get("used_fallback"):
        lines += ["", "(Template reply used because the AI draft was unavailable.)"]
    return "\n".join(lines)


def process_enquiry(raw: dict, deps: dict) -> dict:
    """Core logic, separated from Lambda so tests can pass in fake AWS calls.

    deps keys: get_firm, save_enquiry, send_email, bedrock_client, model_id,
    approve_base_url
    """
    firm_id = str(raw.get("firm_id", ""))[:64]
    firm = deps["get_firm"](firm_id) if firm_id else None
    if not firm:
        raise ValidationError("Unknown firm")

    enquiry = validate_enquiry(raw)
    estimate = estimate_fee(enquiry, firm)
    result = score_enquiry(enquiry, firm)

    draft = draft_reply(enquiry, firm, result, estimate, deps["bedrock_client"], deps["model_id"])

    # If the AI spotted red flags, re-score. An "accept" becomes "review",
    # and we redraft so the prospect does not get a reply quoting a fee.
    if draft["flags"]:
        new_result = score_enquiry(enquiry, firm, ai_flags=draft["flags"])
        if new_result["decision"] != result["decision"]:
            flags = draft["flags"]
            result = new_result
            draft = draft_reply(enquiry, firm, result, estimate, deps["bedrock_client"], deps["model_id"])
            draft["flags"] = flags

    # Hard rule: nothing goes to the prospect automatically. The reply is
    # saved as a draft, and the partner approves it from a link in their email.
    # The token is a long random secret, so only someone with the link can send.
    token = secrets.token_urlsafe(24)

    # Save first, so the enquiry is never lost even if sending email fails.
    created = deps["save_enquiry"](firm_id, {
        "enquiry": enquiry,
        "decision": result["decision"],
        "score": result["score"],
        "reasons": result["reasons"],
        "flags": draft["flags"],
        "estimate_low": estimate["low"],
        "estimate_high": estimate["high"],
        "draft_subject": draft["reply_subject"],
        "draft_body": draft["reply_body"],
        "status": "awaiting_approval",
        "approval_token": token,
    })

    approve_url = (
        f"{deps['approve_base_url']}?"
        + urlencode({"f": firm_id, "c": created, "t": token})
    )

    deps["send_email"](
        firm["partner_email"],
        f"[{result['decision'].upper()}] New enquiry from {enquiry['name']}",
        _partner_email(enquiry, result, estimate, draft, approve_url),
        reply_to=enquiry["email"],
    )
    return result


def handler(event, context):
    try:
        raw = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"error": "Invalid request"})

    deps = {
        "get_firm": aws_io.get_firm,
        "save_enquiry": aws_io.save_enquiry,
        "send_email": aws_io.send_email,
        "bedrock_client": _bedrock_client(),
        "model_id": os.environ.get("BEDROCK_MODEL_ID"),
        # Work out the approval page address from the request that just came
        # in, since it arrived through the same API. (Putting the API's address
        # in the function's settings creates a circular dependency in
        # CloudFormation: the API needs the function, and the function would
        # need the API.)
        "approve_base_url": f"https://{event.get('requestContext', {}).get('domainName', 'unknown-host')}/approve",
    }

    try:
        process_enquiry(raw, deps)
    except ValidationError as exc:
        if str(exc) == "spam":
            # Pretend it worked so bots learn nothing.
            return _response(200, {"message": "Thanks, we have received your enquiry."})
        return _response(400, {"error": str(exc)})
    except Exception as exc:  # noqa: BLE001
        print(f"Unhandled error: {exc!r}")
        return _response(500, {"error": "Something went wrong. Please email us directly."})

    # The prospect never sees their score or decision.
    return _response(200, {"message": "Thanks, we have received your enquiry and will be in touch soon."})
