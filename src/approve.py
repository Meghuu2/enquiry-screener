"""Lambda handler: GET and POST /approve

The partner's email contains a link like /approve?f=<firm>&c=<enquiry>&t=<token>.

GET  shows a page with the draft reply in editable boxes and a Send button.
POST (the Send button) checks the token, sends the edited reply once, and
marks the enquiry as sent.

Why two steps instead of "click the link and it sends"? Work email systems
such as Outlook's Safe Links automatically open every link in an email to scan
it for viruses. A link that sent on GET would fire before the partner had even
read it. Sending only on a button press (POST) avoids that.
"""
import base64
import hmac
import html
from urllib.parse import parse_qs

import aws_io

MAX_SUBJECT = 200
MAX_BODY = 5000


def _page(title: str, inner: str, status: int = 200) -> dict:
    doc = f"""<!DOCTYPE html>
<html lang="en-GB"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{html.escape(title)}</title>
<style>
 body {{ font-family: system-ui, sans-serif; max-width: 680px; margin: 40px auto; padding: 0 20px; color: #1d2433; }}
 h1 {{ font-size: 1.4rem; }}
 .meta {{ background: #f3f4f6; padding: 12px 14px; border-radius: 8px; font-size: .92rem; line-height: 1.5; }}
 label {{ display: block; font-weight: 600; margin: 18px 0 6px; }}
 input, textarea {{ width: 100%; box-sizing: border-box; padding: 10px; border: 1px solid #d1d5db; border-radius: 6px; font: inherit; }}
 textarea {{ min-height: 260px; }}
 button {{ margin-top: 18px; padding: 12px 20px; border: 0; border-radius: 6px; background: #1f5f4a; color: #fff; font: 600 1rem system-ui; cursor: pointer; }}
</style></head><body>{inner}</body></html>"""
    return {"statusCode": status, "headers": {"Content-Type": "text/html; charset=utf-8"}, "body": doc}


def _params(event: dict) -> dict:
    """Read f, c, t (and subject/body on POST) from the query string or form body."""
    params = {k: v for k, v in (event.get("queryStringParameters") or {}).items()}
    if event.get("requestContext", {}).get("http", {}).get("method") == "POST":
        body = event.get("body") or ""
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body).decode("utf-8")
        params.update({k: v[0] for k, v in parse_qs(body).items()})
    return params


def _load_and_check(params: dict, deps: dict):
    """Return the enquiry record if the link is valid, else None."""
    firm_id, created, token = params.get("f", ""), params.get("c", ""), params.get("t", "")
    if not (firm_id and created and token):
        return None
    record = deps["get_enquiry"](firm_id, created)
    if not record or not record.get("approval_token"):
        return None
    # compare_digest takes the same time whether the token is close or not,
    # so an attacker cannot guess it character by character from timings.
    if not hmac.compare_digest(record["approval_token"], token):
        return None
    return record


def show_draft(params: dict, deps: dict) -> dict:
    record = _load_and_check(params, deps)
    if not record:
        return _page("Link not valid", "<h1>This link is not valid or has expired.</h1>", 404)

    e = record["enquiry"]
    if record.get("status") == "sent":
        return _page("Already sent", f"<h1>Already sent</h1><p>This reply to "
                     f"{html.escape(e['name'])} has already been sent.</p>")

    # Everything shown is escaped, because the draft is partly based on text
    # typed by a member of the public and could contain HTML or script tags.
    esc = html.escape
    reasons = "<br>".join(esc(r) for r in record.get("reasons", [])) or "No rules matched."
    flags = ", ".join(esc(f) for f in record.get("flags", []))
    inner = f"""
<h1>Reply to {esc(e['name'])}</h1>
<div class="meta">
 <b>Decision:</b> {esc(record['decision'].upper())} (score {record['score']}/100)<br>
 <b>Email:</b> {esc(e['email'])}<br>
 <b>Fee estimate:</b> £{record['estimate_low']:,} to £{record['estimate_high']:,}<br>
 <b>Why:</b><br>{reasons}
 {f'<br><b>Flags:</b> {flags}' if flags else ''}
</div>
<form method="post">
 <input type="hidden" name="f" value="{esc(params['f'])}">
 <input type="hidden" name="c" value="{esc(params['c'])}">
 <input type="hidden" name="t" value="{esc(params['t'])}">
 <label for="subject">Subject</label>
 <input id="subject" name="subject" maxlength="{MAX_SUBJECT}" value="{esc(record['draft_subject'])}">
 <label for="body">Message</label>
 <textarea id="body" name="body" maxlength="{MAX_BODY}">{esc(record['draft_body'])}</textarea>
 <button type="submit">Send this reply to {esc(e['name'].split()[0])}</button>
</form>"""
    return _page(f"Reply to {e['name']}", inner)


def send_approved(params: dict, deps: dict) -> dict:
    record = _load_and_check(params, deps)
    if not record:
        return _page("Link not valid", "<h1>This link is not valid or has expired.</h1>", 404)

    subject = (params.get("subject") or record["draft_subject"]).strip()[:MAX_SUBJECT]
    body = (params.get("body") or record["draft_body"]).strip()[:MAX_BODY]
    firm = deps["get_firm"](params["f"])
    e = record["enquiry"]

    if not deps["claim_for_sending"](params["f"], params["c"], subject, body):
        return _page("Already sent", "<h1>Already sent</h1><p>This reply was already sent.</p>")

    try:
        deps["send_email"](e["email"], subject, body, reply_to=firm["partner_email"])
    except Exception as exc:  # noqa: BLE001
        print(f"Send failed: {exc!r}")
        deps["release_claim"](params["f"], params["c"])
        return _page("Not sent", "<h1>Sending failed</h1><p>Nothing was sent. Please try again.</p>", 502)

    return _page("Sent", f"<h1>Sent</h1><p>Your reply to {html.escape(e['name'])} is on its way.</p>")


def handler(event, context):
    deps = {
        "get_enquiry": aws_io.get_enquiry,
        "get_firm": aws_io.get_firm,
        "claim_for_sending": aws_io.claim_for_sending,
        "release_claim": aws_io.release_claim,
        "send_email": aws_io.send_email,
    }
    params = _params(event)
    if event.get("requestContext", {}).get("http", {}).get("method") == "POST":
        return send_approved(params, deps)
    return show_draft(params, deps)
