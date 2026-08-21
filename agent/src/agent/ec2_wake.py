"""Ensure an EC2 instance is running before SSH, and track last_up."""

import io
import socket
import time

import boto3
import paramiko
from botocore.config import Config as BotoConfig
from loguru import logger

from storage.entity.dto import VmConfig
from storage.service import vm_config as vm_service


# If last_up is older than this, assume the VM may be stopped/hibernated.
IDLE_THRESHOLD_SECONDS = 60

# EC2 calls run in a thread their caller cannot cancel (ssh_exec's prelude,
# the usage-limit sweep's sleep-state probe), so the transport carries its own
# bound (todo 3226). botocore defaults to a 60s read timeout with up to five
# attempts; capped here so one EC2 call ends in about half a minute instead of
# several. This bounds a single API call only — how long a *wake* may take is
# unchanged.
_EC2_CLIENT_CONFIG = BotoConfig(
    connect_timeout=5,
    read_timeout=10,
    retries={"max_attempts": 2, "mode": "standard"},
)

# How long a *single* readiness probe may hang. Deliberately only the
# per-connection bound: the number of attempts and the interval between them
# are the wake path's acceptance envelope for a legitimately slow cold boot
# (interactive chat, terminal, image transfer and Telegram delivery all wake
# VMs this way), not a transport bound, and are left as they were: a hung
# probe now costs one attempt instead of most of the envelope, and the
# envelope itself still accepts the same slow boots. The usage-limit sweep
# never reaches here at all — it checks `is_vm_asleep` and reports
# `vm_unreachable` instead of waking anything.
_SSH_READY_CONNECT_TIMEOUT_SECONDS = 5


def _ec2_client(region: str):
    return boto3.client("ec2", region_name=region, config=_EC2_CLIENT_CONFIG)


def _is_stale(last_up: int | None) -> bool:
    """Return True if last_up is None or older than IDLE_THRESHOLD_SECONDS."""
    if not last_up:
        return True
    return (int(time.time()) - last_up) > IDLE_THRESHOLD_SECONDS


def get_instance_state(instance_id: str, region: str) -> str:
    """Read-only EC2 instance state ('running', 'stopped', ...). Never starts
    the instance, unlike _start_and_wait / ensure_vm_running."""
    ec2 = _ec2_client(region)
    resp = ec2.describe_instance_status(
        InstanceIds=[instance_id],
        IncludeAllInstances=True,
    )
    statuses = resp.get("InstanceStatuses", [])
    return statuses[0]["InstanceState"]["Name"] if statuses else "unknown"


def is_vm_asleep(vm_config: VmConfig) -> bool:
    """True if the VM has EC2 config and is not currently running. Read-only:
    never wakes the instance, unlike ensure_vm_running. Callers that must not
    trigger a wake (e.g. a polled status read) should check this first and
    skip SSH entirely rather than let ssh_exec's ensure_and_touch_vm wake it."""
    if not vm_config.ec2_instance_id or not vm_config.ec2_region:
        return False
    return get_instance_state(vm_config.ec2_instance_id, vm_config.ec2_region) != "running"


def _start_and_wait(instance_id: str, region: str) -> None:
    """Start an EC2 instance and wait until it's running."""
    ec2 = _ec2_client(region)

    state = get_instance_state(instance_id, region)

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


def _wait_for_ssh(vm_config: VmConfig, max_attempts: int = 36, interval: float = 5) -> None:
    """Try connecting via SSH until successful, up to roughly three minutes."""
    user, host, port = _parse_ssh_target(vm_config.vm_name)
    key = paramiko.Ed25519Key.from_private_key(io.StringIO(vm_config.api_token))

    for attempt in range(1, max_attempts + 1):
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                host, port=port, username=user, pkey=key,
                timeout=_SSH_READY_CONNECT_TIMEOUT_SECONDS,
                # Without these a host that accepts the TCP connection and then
                # says nothing holds the probe for paramiko's own 15s/30s
                # defaults, per attempt.
                banner_timeout=_SSH_READY_CONNECT_TIMEOUT_SECONDS,
                auth_timeout=_SSH_READY_CONNECT_TIMEOUT_SECONDS,
            )
            client.close()
            logger.info("ec2_wake: SSH ready after {} attempt(s)", attempt)
            return
        except (paramiko.SSHException, socket.error, OSError) as e:
            logger.info("ec2_wake: SSH not ready (attempt {}/{}): {}", attempt, max_attempts, e)
            if attempt < max_attempts:
                time.sleep(interval)

    raise TimeoutError(f"ec2_wake: SSH did not become ready after {max_attempts} attempts")


def ensure_vm_running(vm_config: VmConfig, user_id: int | None = None) -> bool:
    """If the VM has EC2 config and last_up is stale, wake the instance."""
    if not vm_config.ec2_instance_id or not vm_config.ec2_region:
        return False

    if not _is_stale(vm_config.last_up):
        return False

    _start_and_wait(vm_config.ec2_instance_id, vm_config.ec2_region)
    if vm_config.vm_name and vm_config.api_token:
        _wait_for_ssh(vm_config)
    return True


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
        if ensure_vm_running(vm_config):
            touch_last_up(vm_config)
