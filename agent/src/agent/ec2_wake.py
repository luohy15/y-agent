"""Ensure an EC2 instance is running before SSH, and track last_up."""

import io
import socket
import time

import boto3
import paramiko
from loguru import logger

from storage.entity.dto import VmConfig
from storage.service import vm_config as vm_service


# If last_up is older than this, assume the VM may be stopped/hibernated.
IDLE_THRESHOLD_SECONDS = 900  # 15 minutes (matches server-side auto-hibernate)


def _is_stale(last_up: int | None) -> bool:
    """Return True if last_up is None or older than IDLE_THRESHOLD_SECONDS."""
    if not last_up:
        return True
    return (int(time.time()) - last_up) > IDLE_THRESHOLD_SECONDS


def _start_and_wait(instance_id: str, region: str) -> None:
    """Start an EC2 instance and wait until it's running."""
    ec2 = boto3.client("ec2", region_name=region)

    resp = ec2.describe_instance_status(
        InstanceIds=[instance_id],
        IncludeAllInstances=True,
    )
    statuses = resp.get("InstanceStatuses", [])
    state = statuses[0]["InstanceState"]["Name"] if statuses else "unknown"

    if state == "running":
        logger.info("ec2_wake: {} already running", instance_id)
        return

    logger.info("ec2_wake: {} is {}, starting...", instance_id, state)
    ec2.start_instances(InstanceIds=[instance_id])

    waiter = ec2.get_waiter("instance_running")
    waiter.wait(InstanceIds=[instance_id])
    logger.info("ec2_wake: {} is now running", instance_id)


def _parse_ssh_target(vm_name: str) -> tuple:
    """Parse 'ssh:user@host:port' or 'ssh:host' into (user, host, port)."""
    raw = vm_name[len("ssh:"):]
    user = None
    port = 22
    if "@" in raw:
        user, raw = raw.split("@", 1)
    if ":" in raw:
        host, port_str = raw.rsplit(":", 1)
        port = int(port_str)
    else:
        host = raw
    return user, host, port


def _wait_for_ssh(vm_config: VmConfig, max_attempts: int = 12, interval: float = 5) -> None:
    """Try connecting via SSH until successful, up to max_attempts * interval seconds."""
    user, host, port = _parse_ssh_target(vm_config.vm_name)
    key = paramiko.Ed25519Key.from_private_key(io.StringIO(vm_config.api_token))

    for attempt in range(1, max_attempts + 1):
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(host, port=port, username=user, pkey=key, timeout=5)
            client.close()
            logger.info("ec2_wake: SSH ready after {} attempt(s)", attempt)
            return
        except (paramiko.SSHException, socket.error, OSError) as e:
            logger.info("ec2_wake: SSH not ready (attempt {}/{}): {}", attempt, max_attempts, e)
            if attempt < max_attempts:
                time.sleep(interval)

    logger.warning("ec2_wake: SSH did not become ready after {} attempts", max_attempts)


def ensure_vm_running(vm_config: VmConfig, user_id: int | None = None) -> None:
    """If the VM has EC2 config and last_up is stale, wake the instance."""
    if not vm_config.ec2_instance_id or not vm_config.ec2_region:
        return

    if not _is_stale(vm_config.last_up):
        return

    _start_and_wait(vm_config.ec2_instance_id, vm_config.ec2_region)
    if vm_config.vm_name and vm_config.api_token:
        _wait_for_ssh(vm_config)


def touch_last_up(vm_config: VmConfig) -> None:
    """Update last_up timestamp in the database."""
    if not vm_config.ec2_instance_id or not vm_config.id:
        return
    now = int(time.time())
    vm_service.update_last_up_by_id(vm_config.id, now)
    vm_config.last_up = now


def ensure_and_touch_vm(vm_config: VmConfig) -> None:
    """Ensure the EC2 VM is running and update last_up timestamp."""
    if vm_config.vm_name and vm_config.vm_name.startswith("ssh:"):
        ensure_vm_running(vm_config)
        touch_last_up(vm_config)
