"""DynamoDB-based process state management for detached claude-code processes."""

import json
import os
import time

import boto3

TABLE_NAME = os.environ.get("DYNAMODB_TABLE", "y-agent-jobs")


def _get_dynamodb():
    return boto3.client("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def register_process(chat_id: str, user_id: int, vm_name: str,
                     bot_name: str = None, trace_id: str = None,
                     skill: str = None, post_hooks: list = None,
                     work_dir: str = None, session_id: str = None,
                     backend_type: str = None) -> None:
    """Register a running tmux process in DynamoDB. status=running, offset=0."""
    now = int(time.time())
    item = {
        "id": {"S": f"proc-{chat_id}"},
        "chat_id": {"S": chat_id},
        "user_id": {"N": str(user_id)},
        "vm_name": {"S": vm_name},
        "status": {"S": "running"},
        "stdout_offset": {"N": "0"},
        "started_at": {"N": str(now)},
        "ttl": {"N": str(now + 86400)},
    }
    if bot_name:
        item["bot_name"] = {"S": bot_name}
    if trace_id:
        item["trace_id"] = {"S": trace_id}
    if skill:
        item["skill"] = {"S": skill}
    if work_dir:
        item["work_dir"] = {"S": work_dir}
    if session_id:
        item["session_id"] = {"S": session_id}
    if post_hooks is not None:
        item["post_hooks"] = {"S": json.dumps(post_hooks)}
    if backend_type:
        item["backend_type"] = {"S": backend_type}

    _get_dynamodb().put_item(TableName=TABLE_NAME, Item=item)


def get_running_processes() -> list:
    """Query all status=running process records via DynamoDB scan."""
    resp = _get_dynamodb().scan(
        TableName=TABLE_NAME,
        FilterExpression="begins_with(id, :prefix) AND #s = :running",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":prefix": {"S": "proc-"},
            ":running": {"S": "running"},
        },
    )
    return [_unpack_item(item) for item in resp.get("Items", [])]


def try_acquire_lease(chat_id: str, owner_id: str, lease_duration: int = 900) -> bool:
    """Try to acquire monitoring lease. Returns True on success.

    Succeeds if: no owner / same owner (renew) / old lease expired.
    """
    now = int(time.time())
    try:
        _get_dynamodb().update_item(
            TableName=TABLE_NAME,
            Key={"id": {"S": f"proc-{chat_id}"}},
            UpdateExpression="SET monitor_owner = :owner, monitor_lease = :lease",
            ConditionExpression=(
                "attribute_not_exists(monitor_owner) "
                "OR monitor_owner = :owner "
                "OR monitor_lease < :now"
            ),
            ExpressionAttributeValues={
                ":owner": {"S": owner_id},
                ":lease": {"N": str(now + lease_duration)},
                ":now": {"N": str(now)},
            },
        )
        return True
    except Exception as e:
        if "ConditionalCheckFailedException" in type(e).__name__:
            return False
        raise


def renew_lease(chat_id: str, owner_id: str, lease_duration: int = 900) -> None:
    """Renew lease (only if we are the current owner)."""
    now = int(time.time())
    _get_dynamodb().update_item(
        TableName=TABLE_NAME,
        Key={"id": {"S": f"proc-{chat_id}"}},
        UpdateExpression="SET monitor_lease = :lease",
        ConditionExpression="monitor_owner = :owner",
        ExpressionAttributeValues={
            ":owner": {"S": owner_id},
            ":lease": {"N": str(now + lease_duration)},
        },
    )


def update_process_offset(chat_id: str, offset: int, last_message_id: str = None,
                          session_id: str = None) -> None:
    """Update the read offset for a process."""
    expr_parts = ["stdout_offset = :offset"]
    values = {":offset": {"N": str(offset)}}
    if last_message_id:
        expr_parts.append("last_message_id = :lmid")
        values[":lmid"] = {"S": last_message_id}
    if session_id:
        expr_parts.append("session_id = :sid")
        values[":sid"] = {"S": session_id}

    _get_dynamodb().update_item(
        TableName=TABLE_NAME,
        Key={"id": {"S": f"proc-{chat_id}"}},
        UpdateExpression="SET " + ", ".join(expr_parts),
        ExpressionAttributeValues=values,
    )


def complete_process(chat_id: str, status: str = "completed") -> None:
    """Mark process as completed/error/interrupted. Clear monitor owner."""
    _get_dynamodb().update_item(
        TableName=TABLE_NAME,
        Key={"id": {"S": f"proc-{chat_id}"}},
        UpdateExpression="SET #s = :status REMOVE monitor_owner, monitor_lease",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":status": {"S": status}},
    )


def _unpack_item(item: dict) -> dict:
    """DynamoDB item -> plain dict."""
    result = {}
    for k, v in item.items():
        if "S" in v:
            result[k] = v["S"]
        elif "N" in v:
            result[k] = int(v["N"]) if "." not in v["N"] else float(v["N"])
        elif "BOOL" in v:
            result[k] = v["BOOL"]
        elif "NULL" in v:
            result[k] = None
    return result
