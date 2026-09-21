"""Ensure an EC2 instance is running before SSH, and track last_up."""

import io
import socket
import threading
import time

import boto3
import paramiko
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError
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

# Per-stage connection bound. Readiness retries use a 180s monotonic budget;
# an already-started probe may finish up to its transport timeouts after it.
# The usage-limit sweep checks is_vm_asleep and never reaches this wake path.
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

    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        try:
            response = ec2.describe_instance_status(
                InstanceIds=[instance_id], IncludeAllInstances=True,
            )
        except ClientError as exc:
            logger.warning("ec2_wake: describe failed while waiting: {}", exc)
        else:
            statuses = response.get("InstanceStatuses", [])
            state = statuses[0]["InstanceState"]["Name"] if statuses else "unknown"
            if state == "running":
                logger.info("ec2_wake: {} is now running", instance_id)
                return
            if state in ("terminated", "shutting-down"):
                raise RuntimeError(f"ec2_wake: instance entered {state}")
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(1, remaining))
    raise TimeoutError("ec2_wake: instance did not become running within 600s")


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


def _wait_for_ssh(vm_config: VmConfig, max_attempts: int = 180, interval: float = 1) -> None:
    """Try connecting via SSH until successful, up to roughly three minutes."""
    user, host, port = _parse_ssh_target(vm_config.vm_name)
    key = paramiko.Ed25519Key.from_private_key(io.StringIO(vm_config.api_token))

    deadline = time.monotonic() + 180
    for attempt in range(1, max_attempts + 1):
        if time.monotonic() >= deadline:
            break
        client = None
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
            logger.info("ec2_wake: SSH ready after {} attempt(s)", attempt)
            return
        except (paramiko.SSHException, socket.error, OSError) as e:
            logger.info("ec2_wake: SSH not ready (attempt {}/{}): {}", attempt, max_attempts, e)
        finally:
            if client is not None:
                client.close()
        remaining = deadline - time.monotonic()
        if attempt < max_attempts and remaining > 0:
            time.sleep(min(interval, remaining))

    raise TimeoutError("ec2_wake: SSH did not become ready within the readiness budget")


def ensure_vm_running(vm_config: VmConfig, user_id: int | None = None) -> bool:
    """If the VM has EC2 config and last_up is stale, wake the instance.

    The throwaway SSH readiness probe still runs on the whole stale branch,
    including already-`running`. EC2 reports running before sshd accepts, and
    callers that connect once with no retry (detach, telegram delivery, images)
    need that gate. Burst cost is cut by single-flighting this prelude, not by
    skipping the probe (todo 3616 C1, review round 1).
    """
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


# Process-local single-flight for the stale-last_up prelude (todo 3616 C1).
# Concurrent callers against one VM share one describe, one readiness probe
# and one last_up write. `_CONFIRMED_UP` covers late joiners that miss the
# in-flight window (a burst larger than the ssh-exec pool).
# `clear_prelude_state` drops both so a caller that has just forced last_up
# stale (tests / replay) still takes the prelude.
_FLIGHTS_GUARD = threading.Lock()
_FLIGHTS: dict[str, dict] = {}
_CONFIRMED_UP: dict[str, int] = {}
# Bound a follower's wait to the documented SSH-ready envelope (~3 minutes).
_PRELUDE_WAIT_SECONDS = 180.0


def _vm_key(vm_config: VmConfig) -> str:
    return vm_config.ec2_instance_id or vm_config.vm_name or ""


def clear_prelude_state(instance_id: str | None = None) -> None:
    """Drop in-flight and confirmed prelude state. Test / replay helper."""
    with _FLIGHTS_GUARD:
        if instance_id is None:
            _FLIGHTS.clear()
            _CONFIRMED_UP.clear()
            return
        _FLIGHTS.pop(instance_id, None)
        _CONFIRMED_UP.pop(instance_id, None)


def _run_prelude(vm_config: VmConfig) -> None:
    if ensure_vm_running(vm_config):
        touch_last_up(vm_config)
        if vm_config.last_up:
            with _FLIGHTS_GUARD:
                _CONFIRMED_UP[_vm_key(vm_config)] = vm_config.last_up


def ensure_and_touch_vm(vm_config: VmConfig) -> None:
    """Ensure the EC2 VM is running and update last_up timestamp.

    Concurrent callers for the same VM join one in-flight prelude (describe,
    SSH readiness, last_up write). last_up is still written on the whole
    stale branch, as it was before this change.
    """
    if not (vm_config.vm_name and vm_config.vm_name.startswith("ssh:")):
        return
    if not vm_config.ec2_instance_id or not vm_config.ec2_region:
        return
    if not _is_stale(vm_config.last_up):
        return

    key = _vm_key(vm_config)
    with _FLIGHTS_GUARD:
        confirmed = _CONFIRMED_UP.get(key)
        if confirmed and not _is_stale(confirmed):
            vm_config.last_up = confirmed
            return
        flight = _FLIGHTS.get(key)
        if flight is None:
            flight = {"event": threading.Event(), "error": None, "last_up": None}
            _FLIGHTS[key] = flight
            leader = True
        else:
            leader = False

    if not leader:
        done = flight["event"].wait(timeout=_PRELUDE_WAIT_SECONDS)
        if done and flight["error"] is None:
            if flight["last_up"]:
                vm_config.last_up = flight["last_up"]
            return
        # Leader still running, or it failed: do not re-raise its exception
        # on this thread. Take the prelude independently so a burst is not
        # all-or-nothing.
        with _FLIGHTS_GUARD:
            confirmed = _CONFIRMED_UP.get(key)
            if confirmed and not _is_stale(confirmed):
                vm_config.last_up = confirmed
                return
        _run_prelude(vm_config)
        return

    try:
        _run_prelude(vm_config)
        flight["last_up"] = vm_config.last_up
    except Exception as exc:
        flight["error"] = exc
        raise
    finally:
        flight["event"].set()
        with _FLIGHTS_GUARD:
            if _FLIGHTS.get(key) is flight:
                del _FLIGHTS[key]
