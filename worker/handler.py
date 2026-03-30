"""Worker Lambda handler — triggered by SQS to run chats."""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from worker.runner import run_chat
from worker.link_downloader import run_link_download


def lambda_handler(event, context):
    """Handle SQS trigger.

    Each SQS record contains a JSON body. The task_type field determines handling:
    - "link_download": download link content via fetcher service
    - default ("chat"): run agent loop for a chat
    BatchSize is 1, so we process one record per invocation.
    """
    records = event.get("Records", [])
    if not records:
        return {"status": "ok", "message": "no records"}

    record = records[0]
    body = json.loads(record["body"])
    task_type = body.get("task_type", "chat")

    if task_type == "link_download":
        print(f"[worker] SQS trigger for link_download link_id={body['link_id']} url={body['url']}")
        asyncio.run(run_link_download(
            user_id=body["user_id"],
            link_id=body["link_id"],
            url=body["url"],
        ))
        return {"status": "ok", "link_id": body["link_id"]}

    # Default: chat task
    chat_id = body["chat_id"]
    bot_name = body.get("bot_name")
    user_id = body.get("user_id")
    vm_name = body.get("vm_name")
    work_dir = body.get("work_dir")
    post_hooks = body.get("post_hooks")
    trace_id = body.get("trace_id")
    skill = body.get("skill")

    print(f"[worker] SQS trigger for chat {chat_id} bot_name={bot_name} user_id={user_id} vm_name={vm_name} work_dir={work_dir} post_hooks={post_hooks}")

    asyncio.run(run_chat(user_id, chat_id, bot_name=bot_name, vm_name=vm_name, work_dir=work_dir, post_hooks=post_hooks, trace_id=trace_id, skill=skill))
    return {"status": "ok", "chat_id": chat_id}
