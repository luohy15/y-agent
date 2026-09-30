"""Worker-side launch preparation. Provider credentials stay in the API."""

from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
import os
import time

from agent.mcp.adapter import request
from storage.service import mcp as svc

STARTUP_DEADLINE_S = 15


@dataclass(repr=False)
class LaunchMaterial:
    summary: dict = field(default_factory=lambda: {"connectors": []})
    context: dict = field(default_factory=dict)
    warning: str = ""
    remote_dir: str | None = None

    @property
    def launch_id(self):
        return self.summary.get("launch_id")


def prepare(user_id, chat_id, run_seq):
    material = LaunchMaterial()
    try:
        svc.end_chat_launches(user_id, chat_id)
        svc.cleanup_expired_state()
        summary, grant = svc.mint_launch(user_id, chat_id, run_seq)
        material.summary = summary
        if not summary["connectors"]:
            if summary["skipped"]:
                material.warning = "Some MCP connectors are unavailable. Check MCP settings and retry or reconnect."
            return material
        url = svc.validate_https_url(os.environ.get("Y_AGENT_MCP_GATEWAY_URL", ""))
        material.context = {"gateway_url": url, "launch_id": summary["launch_id"], "grant": grant}
        # One 15s startup budget; each probe's socket timeout is what is left
        # of it, so no probe thread outlives the deadline by more than a read.
        end_at = time.monotonic() + STARTUP_DEADLINE_S

        def probe(item):
            left = end_at - time.monotonic()
            if left <= 0:
                raise TimeoutError("startup deadline reached")
            return request({**material.context, "connector_id": item["connector_id"]},
                           "tools/list", {}, timeout=left)

        executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="mcp-launch")
        futures = {executor.submit(probe, item): item for item in summary["connectors"]}
        done, pending = wait(futures, timeout=STARTUP_DEADLINE_S)
        available = []
        for future, item in futures.items():
            if future in done:
                try:
                    future.result()
                    available.append(item)
                    continue
                except Exception:
                    pass
            future.cancel()
            # Terminal: outside the staged config, and the grant stops covering
            # it. If this cannot be recorded the whole launch fails closed below.
            svc.exclude_launch_connector(
                summary["launch_id"], item["connector_id"],
                error_code="provider_unavailable" if future in done else "timeout")
        executor.shutdown(wait=False, cancel_futures=True)
        material.summary = {**summary, "connectors": available}
        if len(available) != len(summary["connectors"]) or summary["skipped"]:
            material.warning = "Some MCP connectors are unavailable. Check MCP settings and retry or reconnect."
    except Exception:
        if material.launch_id:
            try:
                svc.end_launch(material.launch_id)
            except Exception:
                pass
        material.summary = {"connectors": []}
        material.context = {}
        material.warning = "MCP connectors could not be loaded. Built-in tools remain available; check MCP settings."
    return material


def end(material):
    if material and material.launch_id:
        svc.end_launch(material.launch_id)
