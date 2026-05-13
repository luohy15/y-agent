"""Shared time-filter CLI flag plumbing (see todo 2052).

Every `y ... list` command exposes the same set of time-filter options:

  --on / --from / --to                — canonical field (entity-specific)
  --created-on / --created-from / --created-to    — created_at
  --updated-on / --updated-from / --updated-to    — updated_at

Inputs accepted:
  YYYY-MM-DD                            (local-tz, full local day on --on / --to)
  YYYY-MM-DDTHH:MM[:SS]                 (local-tz, exact instant)

Rules:
  * `--on` is mutually exclusive with `--from` / `--to` within the same group.
  * At most one group (canonical / created / updated) may be used per invocation.
  * Date input on `--to` covers the whole local day (next-day-start exclusive).
"""

import click


_GROUPS = (
    ("", "on", "from_", "to"),
    ("created", "created_on", "created_from", "created_to"),
    ("updated", "updated_on", "updated_from", "updated_to"),
)


def time_filter_options(f):
    """Decorator that adds the standard time-filter flags to a click command."""
    f = click.option('--updated-to', 'updated_to', default=None,
                     help='Filter by updated_at (date input → closed day; datetime → exclusive)')(f)
    f = click.option('--updated-from', 'updated_from', default=None,
                     help='Lower bound on updated_at (inclusive)')(f)
    f = click.option('--updated-on', 'updated_on', default=None,
                     help='Filter updated_at to a single local-tz date (YYYY-MM-DD)')(f)
    f = click.option('--created-to', 'created_to', default=None,
                     help='Filter by created_at (date input → closed day; datetime → exclusive)')(f)
    f = click.option('--created-from', 'created_from', default=None,
                     help='Lower bound on created_at (inclusive)')(f)
    f = click.option('--created-on', 'created_on', default=None,
                     help='Filter created_at to a single local-tz date (YYYY-MM-DD)')(f)
    f = click.option('--to', 'to', default=None,
                     help='Upper bound on canonical timestamp (date → closed day; datetime → exclusive)')(f)
    f = click.option('--from', 'from_', default=None,
                     help='Lower bound on canonical timestamp (inclusive)')(f)
    f = click.option('--on', 'on', default=None,
                     help='Filter canonical timestamp to a single local-tz date (YYYY-MM-DD)')(f)
    return f


def collect_time_params(
    on=None, from_=None, to=None,
    created_on=None, created_from=None, created_to=None,
    updated_on=None, updated_from=None, updated_to=None,
):
    """Validate the time-filter flags and return non-None params for api_request.

    Raises click.UsageError on conflicting flags. The returned dict uses
    query-string keys (`from` not `from_`) so it can be merged directly into
    api_request `params=`.
    """
    values = {
        "": (on, from_, to),
        "created": (created_on, created_from, created_to),
        "updated": (updated_on, updated_from, updated_to),
    }
    active = [g for g, vs in values.items() if any(v is not None for v in vs)]
    if len(active) > 1:
        labels = {"": "--on/--from/--to", "created": "--created-*", "updated": "--updated-*"}
        names = ", ".join(labels[g] for g in active)
        raise click.UsageError(f"Conflicting time filters: {names} cannot be combined.")
    for g, (g_on, g_from, g_to) in values.items():
        if g_on is not None and (g_from is not None or g_to is not None):
            prefix = f"--{g}-" if g else "--"
            raise click.UsageError(
                f"{prefix}on is mutually exclusive with {prefix}from/{prefix}to"
            )
    params = {}
    if on is not None:
        params["on"] = on
    if from_ is not None:
        params["from"] = from_
    if to is not None:
        params["to"] = to
    if created_on is not None:
        params["created_on"] = created_on
    if created_from is not None:
        params["created_from"] = created_from
    if created_to is not None:
        params["created_to"] = created_to
    if updated_on is not None:
        params["updated_on"] = updated_on
    if updated_from is not None:
        params["updated_from"] = updated_from
    if updated_to is not None:
        params["updated_to"] = updated_to
    return params
