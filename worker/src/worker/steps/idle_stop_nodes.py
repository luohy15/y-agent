"""Hibernate idle Linux nodes. An incomplete view of activity never permits a stop."""

import time
from collections import defaultdict
from datetime import datetime, timezone

from loguru import logger

from agent.chat_target import _parse_address, _connect
from agent.ec2_wake import STOP_LOCK_SECONDS, _ec2_client
from storage.repository import pipeline_lock, vm_config
from storage.service.vm_config import idle_stop_action, normalize_node_name
from worker.process_manager import get_running_processes


def _endpoint(node):
    addr = _parse_address(node.vm_name)
    return f"{addr[1].lower()}:{addr[2]}" if addr else None


def plan_stops(rows, work, now):
    groups = defaultdict(list)
    locations = defaultdict(set)
    names = {(owner, node.name) for owner, node in rows}
    work = {(owner, normalize_node_name(target)) for owner, target in work}
    unknown = {owner for owner, target in work if (owner, target) not in names}
    active_owners = {owner for owner, _ in work}
    anchors = {owner: _endpoint(node) for owner, node in rows if node.name == "default" and node.ec2_instance_id}
    for owner, node in rows:
        endpoint = _endpoint(node)
        locations[node.ec2_region, node.ec2_instance_id].add(endpoint)
        if endpoint:
            groups[endpoint].append((owner, node))
    result = {}
    for endpoint, members in groups.items():
        identities = {(node.ec2_region, node.ec2_instance_id) for _, node in members
                      if node.ec2_instance_id or node.ec2_region}
        cannot_wake = any(not node.ec2_instance_id and anchors.get(owner) != endpoint for owner, node in members)
        if cannot_wake or len(identities) != 1 or any(not region or not instance for region, instance in identities):
            reason = "missing_or_conflicting_ec2"
        elif len(locations[next(iter(identities))]) != 1:
            reason = "ambiguous_endpoint"
        elif any(node.platform not in (None, "linux") for _, node in members):
            reason = "unsupported_platform"
        elif any(owner in unknown or (owner, node.name) in work or
                 (node.name == "default" and owner in active_owners) for owner, node in members):
            reason = "running_work"
        elif any(node.last_active_at is not None and now - node.last_active_at < 900 for _, node in members):
            reason = "recent_activity"
        else:
            reason = "idle"
        result[endpoint] = reason
    return result


def _snapshot():
    rows, chats = vm_config.idle_snapshot()
    work = list(chats) + [(int(proc["user_id"]), proc.get("target_id")) for proc in get_running_processes()]
    return rows, plan_stops(rows, work, int(time.time()))


def _probe(rows, owner, node):
    """Count established sshd connections; exactly one must be our own probe."""
    anchor = next(config for uid, config in rows if uid == owner and config.name == "default")
    user, host, port = _parse_address(node.vm_name)
    outer = client = None
    try:
        channel = None
        if node.name != "default":
            anchor_user, anchor_host, anchor_port = _parse_address(anchor.vm_name)
            outer = _connect(anchor_host, anchor_port, anchor_user, anchor.api_token)
            channel = outer.get_transport().open_channel("direct-tcpip", (host, port), ("127.0.0.1", 0), timeout=5)
        client = _connect(host, port, user, node.api_token or anchor.api_token, sock=channel)
        _, stdout, _ = client.exec_command(f"ss -Htn state established '( sport = :{port} )'", timeout=5)
        lines = stdout.readlines()
        return stdout.channel.recv_exit_status() == 0 and len(lines) == 1
    finally:
        if client:
            client.close()
        if outer:
            outer.close()


def _consider(rows, owner, node, endpoint, dry_run):
    action = idle_stop_action(node)
    if not pipeline_lock.try_acquire_exclusive_lock(action, STOP_LOCK_SECONDS):
        return "locked"
    try:
        ec2 = _ec2_client(node.ec2_region)
        ids = [node.ec2_instance_id]
        instance = ec2.describe_instances(InstanceIds=ids)["Reservations"][0]["Instances"][0]
        if not _bound_endpoint(instance, endpoint):
            return "unverified_endpoint"
        if instance["State"]["Name"] == "stopped":
            return "already_stopped"
        if instance["State"]["Name"] != "running" or not instance["HibernationOptions"]["Configured"]:
            return "not_running_or_not_configured"
        if not _probe(rows, owner, node):
            return "ssh_busy_or_unknown"
        current, decisions = _snapshot()
        members = {(uid, config.id, config.name, config.ec2_region, config.ec2_instance_id, config.vm_name)
                   for uid, config in rows if _endpoint(config) == endpoint}
        current_members = {(uid, config.id, config.name, config.ec2_region, config.ec2_instance_id, config.vm_name)
                           for uid, config in current if _endpoint(config) == endpoint}
        if decisions.get(endpoint) != "idle" or current_members != members:
            return "changed"
        if dry_run:
            return "would_hibernate"
        pipeline_lock.set_marker(action, "stop_requested", datetime.now(timezone.utc))
        ec2.stop_instances(InstanceIds=ids, Hibernate=True)
        ec2.get_waiter("instance_stopped").wait(InstanceIds=ids, WaiterConfig={"Delay": 3, "MaxAttempts": 100})
        return "hibernated"
    finally:
        pipeline_lock.release_lock(action)


def _bound_endpoint(instance, endpoint):
    """Tenant-editable config alone is not authority to stop an EC2 instance."""
    host, _, port = endpoint.rpartition(":")
    if port == "22" and host in {instance.get(field, "").lower() for field in
                                 ("PrivateIpAddress", "PrivateDnsName", "PublicIpAddress", "PublicDnsName")}:
        return True
    return any(tag["Key"] == "y-agent:ssh-endpoint" and tag["Value"].lower() == endpoint
               for tag in instance.get("Tags", ()))


def handle_idle_stop_nodes(*, dry_run=False):
    rows, decisions = _snapshot()
    anchors = {owner: _endpoint(node) for owner, node in rows if node.name == "default"}
    children = defaultdict(set)
    pending = {}
    for owner, node in sorted(rows, key=lambda row: row[1].name != "default"):
        endpoint = _endpoint(node)
        if not endpoint or not node.ec2_instance_id or node.platform not in ("linux", None):
            continue
        if anchors.get(owner) != endpoint:
            children[anchors.get(owner)].add(endpoint)
        if decisions.get(endpoint) == "idle":
            pending.setdefault(endpoint, (owner, node))
    cleared = {"already_stopped", "hibernated"} | ({"would_hibernate"} if dry_run else set())
    while pending:
        ready = [endpoint for endpoint in pending
                 if all(decisions.get(child) in cleared for child in children[endpoint])]
        if not ready:
            decisions.update(dict.fromkeys(pending, "dependent_not_stopped"))
            break
        for endpoint in ready:
            owner, node = pending.pop(endpoint)
            try:
                decisions[endpoint] = _consider(rows, owner, node, endpoint, dry_run)
            except Exception as exc:
                decisions[endpoint] = f"unknown:{type(exc).__name__}"
    logger.info("idle-stop dry_run={} decisions={}", dry_run, decisions)
    return {"dry_run": dry_run, "decisions": decisions}
