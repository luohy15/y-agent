"""Private stdio MCP adapter. Standard library only; staged with each launch."""

import http.client
import json
import os
import ssl
import stat
import sys
import threading
from urllib.parse import urlsplit

MAX_BYTES = 8 * 1024 * 1024
METHODS = {"initialize", "notifications/initialized", "ping", "tools/list", "tools/call"}


def read_context(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
            raise ValueError("invalid private context")
        context = json.loads(stream.read(65537))
    url = urlsplit(context["gateway_url"])
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError("invalid gateway")
    return context


def request(context, method, params, timeout=40):
    url = urlsplit(context["gateway_url"])
    connection = http.client.HTTPSConnection(url.hostname, url.port or 443, timeout=timeout,
                                            context=ssl.create_default_context())
    try:
        body = json.dumps({"connector_id": context["connector_id"], "method": method, "params": params})
        connection.request("POST", url.path.rstrip('/') + '/' + context['launch_id'], body,
                           {"Authorization": "Bearer " + context["grant"], "Content-Type": "application/json"})
        response = connection.getresponse()
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES or response.status != 200:
            raise ValueError("connector unavailable")
        data = json.loads(raw)
        if not isinstance(data.get("result"), dict):
            raise ValueError("invalid gateway response")
        return data["result"]
    finally:
        connection.close()


def serve(context, source, sink, call=request):
    stopped = threading.Event()

    def heartbeat():
        while not stopped.wait(300):
            try:
                call(context, "ping", {})
            except Exception:
                pass

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        while True:
            line = source.readline(MAX_BYTES + 1)
            if not line:
                break
            if len(line) > MAX_BYTES:
                break
            rid = None
            try:
                message = json.loads(line)
                if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                    raise ValueError("invalid request")
                rid = message.get("id")
                method = message.get("method")
                if method not in METHODS:
                    response = {"error": {"code": -32601, "message": "MCP method is not available"}}
                else:
                    result = call(context, method, message.get("params", {}))
                    response = {"result": result}
                if "id" not in message:
                    continue
            except Exception:
                response = {"error": {"code": -32000,
                            "message": "Connector unavailable. Retry or reconnect in MCP settings."}}
            sink.write(json.dumps({"jsonrpc": "2.0", "id": rid, **response}) + "\n")
            sink.flush()
    finally:
        stopped.set()


def main():
    try:
        serve(read_context(sys.argv[1]), sys.stdin, sys.stdout)
    except Exception:
        print("MCP connector unavailable; check MCP settings.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
