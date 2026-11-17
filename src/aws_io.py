"""Thin wrappers around DynamoDB and SES.

Keeping AWS calls in one small module means the business logic can be tested
without AWS, by passing in fake versions of these functions.
"""
import json
import os
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "180"))

_dynamodb = None
_ses = None


def _db():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb")
    return _dynamodb


def _ses_client():
    global _ses
    if _ses is None:
        _ses = boto3.client("sesv2")
    return _ses


def _to_plain(item):
    """DynamoDB returns numbers as Decimal. Convert back to int/float."""
    return json.loads(json.dumps(item, default=lambda d: int(d) if d % 1 == 0 else float(d)))


def _to_dynamo(item):
    """DynamoDB rejects Python floats. Convert them to Decimal."""
    return json.loads(json.dumps(item), parse_float=Decimal)


def get_firm(firm_id: str) -> dict | None:
    table = _db().Table(os.environ["FIRMS_TABLE"])
    item = table.get_item(Key={"firm_id": firm_id}).get("Item")
    return _to_plain(item) if item else None


def list_firms() -> list[dict]:
    table = _db().Table(os.environ["FIRMS_TABLE"])
    items, kwargs = [], {}
    while True:
        page = table.scan(**kwargs)
        items.extend(page.get("Items", []))
        if "LastEvaluatedKey" not in page:
            return [_to_plain(i) for i in items]
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def save_enquiry(firm_id: str, record: dict) -> str:
    table = _db().Table(os.environ["ENQUIRIES_TABLE"])
    now = datetime.now(timezone.utc)
    sort_key = f"{now.isoformat()}#{uuid.uuid4().hex[:8]}"
    item = {
        "firm_id": firm_id,
        "created": sort_key,
        # TTL: DynamoDB deletes the record automatically after the retention
        # period, which supports the GDPR principle of not keeping data forever.
        "expires_at": int(time.time()) + RETENTION_DAYS * 86400,
        **record,
    }
    table.put_item(Item=_to_dynamo(item))
    return sort_key


def enquiries_since(firm_id: str, since_iso: str) -> list[dict]:
    table = _db().Table(os.environ["ENQUIRIES_TABLE"])
    items, kwargs = [], {"KeyConditionExpression": Key("firm_id").eq(firm_id) & Key("created").gte(since_iso)}
    while True:
        page = table.query(**kwargs)
        items.extend(page.get("Items", []))
        if "LastEvaluatedKey" not in page:
            return [_to_plain(i) for i in items]
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def get_enquiry(firm_id: str, created: str) -> dict | None:
    table = _db().Table(os.environ["ENQUIRIES_TABLE"])
    item = table.get_item(Key={"firm_id": firm_id, "created": created}).get("Item")
    return _to_plain(item) if item else None


def claim_for_sending(firm_id: str, created: str, subject: str, body: str) -> bool:
    """Mark a draft as sent, only if it is still awaiting approval.

    The condition makes this atomic: if the partner double-clicks, or two
    people approve at once, only one request wins and the email goes once.
    """
    table = _db().Table(os.environ["ENQUIRIES_TABLE"])
    try:
        table.update_item(
            Key={"firm_id": firm_id, "created": created},
            UpdateExpression="SET #s = :sent, sent_subject = :subj, sent_body = :body",
            ConditionExpression="#s = :waiting",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":sent": "sent", ":waiting": "awaiting_approval",
                ":subj": subject, ":body": body,
            },
        )
        return True
    except _db().meta.client.exceptions.ConditionalCheckFailedException:
        return False


def release_claim(firm_id: str, created: str) -> None:
    """Undo claim_for_sending if the email then failed, so it can be retried."""
    table = _db().Table(os.environ["ENQUIRIES_TABLE"])
    table.update_item(
        Key={"firm_id": firm_id, "created": created},
        UpdateExpression="SET #s = :waiting",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":waiting": "awaiting_approval"},
    )


def send_email(to: str, subject: str, body: str, reply_to: str | None = None) -> None:
    kwargs = {
        "FromEmailAddress": os.environ["SENDER_EMAIL"],
        "Destination": {"ToAddresses": [to]},
        "Content": {"Simple": {
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
        }},
    }
    if reply_to:
        kwargs["ReplyToAddresses"] = [reply_to]
    _ses_client().send_email(**kwargs)
