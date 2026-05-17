"""Shared Telegram delivery helpers for chat images."""

import os
import tempfile
from urllib.parse import urlparse

from loguru import logger

from agent.ec2_wake import ensure_and_touch_vm
from agent.ssh_pool import SSHPool
from storage.util import send_telegram_photo


def send_telegram_photo_reference(
    bot_token: str,
    tg_chat_id,
    image_path: str,
    caption: str | None = None,
    topic_id=None,
    vm_config=None,
    ssh_client=None,
) -> bool:
    parsed = urlparse(image_path)
    scheme = parsed.scheme.lower()
    if scheme in {"http", "https"}:
        send_telegram_photo(bot_token, tg_chat_id, image_path, caption=caption, message_thread_id=topic_id)
        return True
    if scheme == "s3":
        logger.warning("telegram photo: skipping legacy s3 image ref {}", image_path)
        return False

    suffix = os.path.splitext(image_path)[1] or ".jpg"
    if ssh_client is not None:
        with tempfile.NamedTemporaryFile(suffix=suffix) as image_file:
            sftp = ssh_client.open_sftp()
            try:
                sftp.get(image_path, image_file.name)
            finally:
                sftp.close()
            image_file.flush()
            send_telegram_photo(bot_token, tg_chat_id, image_file.name, caption=caption, message_thread_id=topic_id)
        return True

    if vm_config is None:
        logger.warning("telegram photo: cannot fetch local image without vm_config: {}", image_path)
        return False

    ensure_and_touch_vm(vm_config)
    pool = SSHPool()
    try:
        client = pool.get_or_create(vm_config)
        return send_telegram_photo_reference(
            bot_token,
            tg_chat_id,
            image_path,
            caption=caption,
            topic_id=topic_id,
            vm_config=vm_config,
            ssh_client=client,
        )
    finally:
        pool.close_all()
