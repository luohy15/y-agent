"""Stage a fixed adapter and private context, never via shell/env exports."""

import hashlib
import json
import os
from pathlib import Path
import uuid

from agent.mcp import adapter


def files(root, summary, context):
    output = {"adapter.py": Path(adapter.__file__).read_text()}
    servers = {}
    for index, connector in enumerate(summary.get("connectors", [])):
        name = f"context-{index}.json"
        output[name] = json.dumps({**context, "connector_id": connector["connector_id"]})
        servers[f"connector_{index}"] = {"type": "stdio", "command": "python3",
                                        "args": [f"{root}/adapter.py", f"{root}/{name}"]}
    output["config.json"] = json.dumps({"mcpServers": servers})
    return output


def write_local(root, summary, context):
    os.chmod(root, 0o700)
    for name, content in files(root, summary, context).items():
        fd = os.open(f"{root}/{name}", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
    return f"{root}/config.json"


def chat_prefix(chat_id):
    return '/tmp/y-mcp-' + hashlib.sha256(chat_id.encode()).hexdigest()[:24] + '-'


def cleanup_command(chat_id):
    # Hash-only pattern cannot include another chat or caller-controlled shell text.
    # find, not a shell glob: the VM login shell is zsh, where an unmatched glob
    # is a hard error (nomatch) and would fail every first launch of a chat.
    name = chat_prefix(chat_id).removeprefix('/tmp/')
    return f"find /tmp/ -maxdepth 1 -name '{name}*' -exec rm -rf -- {{}} +"


def stage_remote(client, summary, context):
    root = f"{chat_prefix(summary['chat_id'])}{uuid.uuid4()}"
    sftp = client.open_sftp()
    created = []
    try:
        # mkdir must succeed exclusively. Never accept an existing directory.
        sftp.mkdir(root, mode=0o700)
        sftp.chmod(root, 0o700)
        for name, content in files(root, summary, context).items():
            path = f"{root}/{name}"
            with sftp.open(path, "wx") as stream:
                created.append(path)
                sftp.chmod(path, 0o600)
                stream.write(content)
        return root
    except Exception:
        for path in created:
            try:
                sftp.remove(path)
            except OSError:
                pass
        try:
            sftp.rmdir(root)
        except OSError:
            pass
        raise RuntimeError("MCP private staging failed") from None
    finally:
        sftp.close()
