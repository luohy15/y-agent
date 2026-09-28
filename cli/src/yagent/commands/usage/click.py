import click

from .backfill import backfill
from .activity_backfill import backfill_activity
from .credentials_cmd import credentials
from .crs_creds import crs_creds
from .limit_history import limit_history
from .limits import limits
from .rate import rate
from .sync import sync
from .transcripts import ingest_transcripts


@click.group("usage")
def usage_group():
    """Provider usage: daily + hourly token/cost ingestion (sync/backfill) plus
    direct-from-provider subscription limit-window reads (credentials/
    limits), and the direct Relay run-rate path (rate / crs-creds)."""


usage_group.add_command(sync)
usage_group.add_command(backfill)
usage_group.add_command(backfill_activity)
usage_group.add_command(credentials)
usage_group.add_command(crs_creds)
usage_group.add_command(limits)
usage_group.add_command(limit_history)
usage_group.add_command(rate)
usage_group.add_command(ingest_transcripts)
