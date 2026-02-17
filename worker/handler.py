"""Worker Lambda handler — triggered by SQS to run chats."""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from worker.runner import run_chat


def lambda_handler(event, context):
    """Handle SQS trigger.

    Each SQS record contains a JSON body with {"chat_id": "...", "bot_name": "..."}.
    BatchSize is 1, so we process one chat per invocation.
    """
    records = event.get("Records", [])
    if not records:
        return {"status": "ok", "message": "no records"}

    record = records[0]
    body = json.loads(record["body"])
    chat_id = body["chat_id"]
    bot_name = body.get("bot_name")
    user_id = body.get("user_id")
    vm_name = body.get("vm_name")

    print(f"[worker] SQS trigger for chat {chat_id} bot_name={bot_name} user_id={user_id} vm_name={vm_name}")

    asyncio.run(run_chat(user_id, chat_id, bot_name=bot_name, vm_name=vm_name))
    return {"status": "ok", "chat_id": chat_id}
