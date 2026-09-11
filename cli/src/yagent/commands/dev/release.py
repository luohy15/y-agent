"""`y dev release` -- project-wide publication ownership (todo 3493).

A claim is a database-enforced single slot per canonical repository: two
sessions cannot both acquire it, and every transition is checked against the
generation and claim id the caller carries. It is *not* a fence around
publication itself -- git, deploy scripts, CI, `y dev commit` and
`y module publish` are unchanged and cooperative, and `check` reports a
point-in-time observation, never a lease.

Unlike the worktree registry, there is no local fallback: an unreachable or
unsupported API is an error, never a successful local claim.
"""

import json
import os
import subprocess
import sys

import click
import httpx

from storage.project_key import ProjectKeyError, normalize_project_key
from yagent.api_client import api_request


def _fail(message: str, payload: dict, as_json: bool, code: int = 1):
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False))
    else:
        click.echo(message, err=True)
    sys.exit(code)


def _git_origin(project_path: str) -> str:
    result = subprocess.run(
        ["git", "-C", project_path, "remote", "get-url", "origin"],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise click.ClickException(f"no git 'origin' remote in {project_path}")
    return result.stdout.strip()


def _resolve_project(project: str, project_path: str) -> str:
    """Canonical project key from an explicit identity or a checkout's origin.

    Never inferred from the branch, the worktree name, an environment or a
    module slug: those must not create a second slot for one repository.
    """
    raw = project or _git_origin(project_path or os.getcwd())
    try:
        return normalize_project_key(raw)
    except ProjectKeyError as exc:
        raise click.ClickException(str(exc))


def _call(method: str, path: str, as_json: bool, **kwargs) -> dict:
    try:
        return api_request(method, path, **kwargs).json()
    except httpx.HTTPStatusError as exc:
        response = exc.response
        try:
            detail = response.json().get("detail")
        except Exception:
            detail = None
        if response.status_code == 404 and not isinstance(detail, dict):
            _fail(
                "this API deployment does not support dev-release; upgrade the API",
                {"error": "unsupported", "status": 404}, as_json,
            )
        if isinstance(detail, dict):
            _fail(_format_error(detail), detail, as_json)
        _fail(f"API error: {exc}", {"error": "api", "status": response.status_code}, as_json)
    except httpx.RequestError as exc:
        # A claim registry that cannot be reached is an error, never a free slot.
        _fail(f"API unreachable: {exc}", {"error": "unreachable"}, as_json)


def _format_slot(slot: dict) -> str:
    if not slot.get("active"):
        return f"{slot['project_key']}  free  generation={slot['generation']}"
    return (
        f"{slot['project_key']}  claimed  generation={slot['generation']}\n"
        f"  claim_id={slot['claim_id']}\n"
        f"  owner={slot.get('owner_user_id')} trace={slot.get('owner_trace_id')} "
        f"chat={slot.get('owner_chat_id')}\n"
        f"  publisher={slot.get('publisher_chat_id') or '-'} target={slot.get('target') or '-'}"
    )


def _format_error(detail: dict) -> str:
    lines = [f"{detail.get('error', 'error')}: {detail.get('reason')}"]
    current = detail.get("current")
    if current:
        lines.append(_format_slot(current))
    return "\n".join(lines)


def _emit(result: dict, as_json: bool, text: str):
    if as_json:
        click.echo(json.dumps(result, ensure_ascii=False))
    else:
        click.echo(text)


def project_options(f):
    f = click.option('--project', default=None,
                     help='Canonical project identity (host/owner/repo) or a GitHub remote URL.')(f)
    f = click.option('--project-path', default=None,
                     help="Checkout whose 'origin' identifies the project (default: cwd).")(f)
    return f


def json_option(f):
    return click.option('--json', 'as_json', is_flag=True,
                        help='Machine-readable output for success and conflict alike.')(f)


@click.group('release')
def release_group():
    """Project-wide publication ownership (enqueue / claim / check / hand off / release)."""
    pass


@release_group.command('status')
@project_options
@json_option
def release_status(project, project_path, as_json):
    """Show the current slot for a project (absent = free at generation 0)."""
    project_key = _resolve_project(project, project_path)
    slot = _call("GET", "/api/dev-release/detail", as_json, params={"project": project_key})
    _emit(slot, as_json, _format_slot(slot))


@release_group.command('list')
@click.option('--limit', default=50, show_default=True, help='Maximum slots to list.')
@json_option
def release_list(limit, as_json):
    """List active claims across projects, for conflict discovery."""
    slots = _call("GET", "/api/dev-release/list", as_json, params={"limit": limit})
    if as_json:
        click.echo(json.dumps(slots, ensure_ascii=False))
        return
    if not slots:
        click.echo("no active claims")
        return
    for slot in slots:
        click.echo(_format_slot(slot))


@release_group.command('claim')
@project_options
@click.option('--trace-id', required=True, help='Owning trace.')
@click.option('--chat-id', required=True, help='Owning chat inside that trace.')
@click.option('--generation', type=int, required=True,
              help='Generation the slot is expected to be at (0 when never claimed).')
@click.option('--request-id', required=True,
              help='Caller-generated UUID; reuse the same value to retry, never a fresh one.')
@click.option('--target', default=None, help='Bounded target metadata (ref / environment).')
@json_option
def release_claim(project, project_path, trace_id, chat_id, generation, request_id, target, as_json):
    """Acquire the project slot. Fails if another claim is active."""
    project_key = _resolve_project(project, project_path)
    body = {"project": project_key, "trace_id": trace_id, "chat_id": chat_id,
            "expected_generation": generation, "request_id": request_id, "target": target}
    result = _call("POST", "/api/dev-release/claim", as_json, json=body)
    _emit(result, as_json, f"claim {result['status']}\n{_format_slot(result['slot'])}")


@release_group.command('check')
@project_options
@click.option('--trace-id', required=True,
              help='Owning trace. Also for --role publisher: the trace is a coordinate of '
                   'the claim, not of the delegate, so a delegate outside that trace still '
                   'passes the owning trace here.')
@click.option('--chat-id', required=True, help='Chat whose role is being tested.')
@click.option('--claim-id', required=True, help='Claim id the caller believes is current.')
@click.option('--generation', type=int, required=True, help='Generation the caller carries.')
@click.option('--role', type=click.Choice(['owner', 'publisher']), required=True,
              help="'owner' tests the coordinating session; 'publisher' tests execution eligibility.")
@json_option
def release_check(project, project_path, trace_id, chat_id, claim_id, generation, role, as_json):
    """Observe eligibility now. Exits nonzero when not eligible."""
    project_key = _resolve_project(project, project_path)
    body = {"project": project_key, "trace_id": trace_id, "chat_id": chat_id,
            "claim_id": claim_id, "expected_generation": generation, "role": role}
    result = _call("POST", "/api/dev-release/check", as_json, json=body)
    if not result["eligible"]:
        _fail(f"not eligible ({role}): {result['reason']}\n{_format_slot(result['slot'])}",
              result, as_json)
    _emit(result, as_json, f"eligible ({role})\n{_format_slot(result['slot'])}")


@release_group.command('release')
@project_options
@click.option('--trace-id', required=True, help='Owning trace.')
@click.option('--chat-id', required=True, help='Owning chat.')
@click.option('--claim-id', required=True, help='Current claim id.')
@click.option('--generation', type=int, required=True, help='Current generation.')
@click.option('--request-id', required=True, help='Caller-generated UUID.')
@click.option('--outcome-reference', required=True,
              help='Terminal outcome of the publication (run URL, deploy record, failure).')
@click.option('--quiescence-evidence', required=True,
              help='Evidence the publisher and its external work have stopped.')
@json_option
def release_release(project, project_path, trace_id, chat_id, claim_id, generation, request_id,
                    outcome_reference, quiescence_evidence, as_json):
    """Release the slot. Requires a terminal outcome and quiescence evidence."""
    project_key = _resolve_project(project, project_path)
    body = {"project": project_key, "trace_id": trace_id, "chat_id": chat_id,
            "claim_id": claim_id, "expected_generation": generation, "request_id": request_id,
            "outcome_reference": outcome_reference, "quiescence_evidence": quiescence_evidence}
    result = _call("POST", "/api/dev-release/release", as_json, json=body)
    _emit(result, as_json, f"release {result['status']}\n{_format_slot(result['slot'])}")


@release_group.command('handoff')
@project_options
@click.option('--trace-id', required=True, help='Owning trace (unchanged by a handoff).')
@click.option('--chat-id', required=True, help='Current owning chat.')
@click.option('--claim-id', required=True, help='Current claim id (kept across the handoff).')
@click.option('--generation', type=int, required=True, help='Current generation.')
@click.option('--request-id', required=True, help='Caller-generated UUID.')
@click.option('--new-owner-chat-id', required=True, help='Successor chat in the same trace.')
@json_option
def release_handoff(project, project_path, trace_id, chat_id, claim_id, generation, request_id,
                    new_owner_chat_id, as_json):
    """Move ownership to a successor chat in the same trace. The slot never opens."""
    project_key = _resolve_project(project, project_path)
    body = {"project": project_key, "trace_id": trace_id, "chat_id": chat_id,
            "claim_id": claim_id, "expected_generation": generation, "request_id": request_id,
            "new_owner_chat_id": new_owner_chat_id}
    result = _call("POST", "/api/dev-release/handoff", as_json, json=body)
    _emit(result, as_json, f"handoff {result['status']}\n{_format_slot(result['slot'])}")


@release_group.command('publisher')
@project_options
@click.option('--trace-id', required=True, help='Owning trace.')
@click.option('--chat-id', required=True, help='Owning chat.')
@click.option('--claim-id', required=True, help='Current claim id.')
@click.option('--generation', type=int, required=True, help='Current generation.')
@click.option('--request-id', required=True, help='Caller-generated UUID.')
@click.option('--publisher-chat-id', default=None,
              help='Chat delegated to execute; omit to clear the delegation.')
@click.option('--quiescence-evidence', default=None,
              help='Required to replace or clear an existing publisher.')
@json_option
def release_publisher(project, project_path, trace_id, chat_id, claim_id, generation, request_id,
                      publisher_chat_id, quiescence_evidence, as_json):
    """Set or clear the single delegated publisher. The owner stays coordinator."""
    project_key = _resolve_project(project, project_path)
    body = {"project": project_key, "trace_id": trace_id, "chat_id": chat_id,
            "claim_id": claim_id, "expected_generation": generation, "request_id": request_id,
            "publisher_chat_id": publisher_chat_id, "quiescence_evidence": quiescence_evidence}
    result = _call("POST", "/api/dev-release/publisher", as_json, json=body)
    _emit(result, as_json, f"publisher {result['status']}\n{_format_slot(result['slot'])}")


@release_group.command('takeover')
@project_options
@click.option('--new-owner-trace-id', required=True, help='Trace taking ownership.')
@click.option('--new-owner-chat-id', required=True, help='Chat taking ownership.')
@click.option('--claim-id', required=True, help='Claim id being displaced.')
@click.option('--generation', type=int, required=True, help='Current generation.')
@click.option('--request-id', required=True, help='Caller-generated UUID.')
@click.option('--authorization-reference', required=True,
              help='Reference to the authorization for this takeover.')
@click.option('--quiescence-evidence', required=True,
              help='Evidence the previous owner/publisher and its external work have stopped.')
@json_option
def release_takeover(project, project_path, new_owner_trace_id, new_owner_chat_id, claim_id,
                     generation, request_id, authorization_reference, quiescence_evidence,
                     as_json):
    """Cross-trace transfer within the same account. Rotates the claim id, clears the publisher."""
    project_key = _resolve_project(project, project_path)
    body = {"project": project_key, "new_owner_trace_id": new_owner_trace_id,
            "new_owner_chat_id": new_owner_chat_id, "claim_id": claim_id,
            "expected_generation": generation, "request_id": request_id,
            "authorization_reference": authorization_reference,
            "quiescence_evidence": quiescence_evidence}
    result = _call("POST", "/api/dev-release/takeover", as_json, json=body)
    _emit(result, as_json, f"takeover {result['status']}\n{_format_slot(result['slot'])}")


@release_group.command('enqueue')
@project_options
@click.option('--trace-id', required=True, help='Coordinator trace taking a turn.')
@click.option('--chat-id', required=True, help='Coordinator chat to wake on grant.')
@click.option('--waiter-id', required=True,
              help='Caller-generated UUID naming this registration; reuse it to retry.')
@click.option('--request-id', required=True, help='Caller-generated UUID for this request.')
@click.option('--authorization-reference', required=True,
              help='Reference to the authorization for the candidate being published.')
@click.option('--baseline-sha', required=True, help='Frozen baseline commit id.')
@click.option('--candidate-sha', required=True, help='Frozen candidate commit id.')
@click.option('--todo', 'todo_ids', multiple=True, required=True,
              help='Todo included in the candidate (repeatable).')
@click.option('--target', default=None, help='Target ref / environment for this turn.')
@json_option
def release_enqueue(project, project_path, trace_id, chat_id, waiter_id, request_id,
                    authorization_reference, baseline_sha, candidate_sha, todo_ids, target,
                    as_json):
    """Take the slot now, or take a place in the queue and wait to be woken.

    One call: if the slot is free you own it, otherwise you are registered in
    FIFO order. When queued, end the turn -- the grant arrives as a message in
    the coordinator chat with ownership already held. No polling, no blocking
    wait, and nothing to ask the user about.
    """
    project_key = _resolve_project(project, project_path)
    body = {"project": project_key, "trace_id": trace_id, "chat_id": chat_id,
            "waiter_id": waiter_id, "request_id": request_id,
            "authorization_reference": authorization_reference,
            "baseline_sha": baseline_sha, "candidate_sha": candidate_sha,
            "todo_ids": list(todo_ids), "target": target}
    result = _call("POST", "/api/dev-release/enqueue", as_json, json=body)
    waiter = result["waiter"]
    summary = f"enqueue {result['status']}"
    if result["status"] != "granted":
        summary += f" waiter={waiter['waiter_id']} state={waiter['status']}"
        if waiter.get("position"):
            summary += f" position={waiter['position']}"
    _emit(result, as_json, f"{summary}\n{_format_slot(result['slot'])}")


@release_group.command('cancel-waiter')
@project_options
@click.option('--trace-id', required=True, help='Registering trace.')
@click.option('--chat-id', required=True, help='Registering chat.')
@click.option('--waiter-id', required=True, help='Waiter UUID to withdraw.')
@click.option('--request-id', required=True, help='Caller-generated UUID for this request.')
@json_option
def release_cancel_waiter(project, project_path, trace_id, chat_id, waiter_id, request_id,
                          as_json):
    """Withdraw a pending registration. An already-granted claim is never released."""
    project_key = _resolve_project(project, project_path)
    body = {"project": project_key, "trace_id": trace_id, "chat_id": chat_id,
            "waiter_id": waiter_id, "request_id": request_id}
    result = _call("POST", "/api/dev-release/cancel-waiter", as_json, json=body)
    _emit(result, as_json,
          f"cancel-waiter {result['status']} waiter={result['waiter']['waiter_id']}")


@release_group.command('waiters')
@project_options
@click.option('--limit', default=50, show_default=True, help='Maximum receipts to list.')
@click.option('--all-projects', is_flag=True, help='List this account across every project.')
@json_option
def release_waiters(project, project_path, limit, all_projects, as_json):
    """This account's waiter receipts: queue position, grant and frozen candidate."""
    params = {"limit": limit}
    if not all_projects:
        params["project"] = _resolve_project(project, project_path)
    waiters = _call("GET", "/api/dev-release/waiters", as_json, params=params)
    if as_json:
        click.echo(json.dumps(waiters, ensure_ascii=False))
        return
    if not waiters:
        click.echo("no waiter receipts")
        return
    for waiter in waiters:
        position = f" position={waiter['position']}" if waiter.get("position") else ""
        click.echo(
            f"{waiter['project_key']}  {waiter['status']}{position}  "
            f"waiter={waiter['waiter_id']} trace={waiter['trace_id']} chat={waiter['chat_id']}\n"
            f"  candidate={waiter['candidate_sha']} baseline={waiter['baseline_sha']} "
            f"todos={','.join(waiter['todo_ids'])} target={waiter.get('target') or '-'}\n"
            f"  authorization={waiter['authorization_reference']}\n"
            f"  claim={waiter.get('granted_claim_id') or '-'} "
            f"delivery={waiter.get('delivery_state') or '-'}"
        )
