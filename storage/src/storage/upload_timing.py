"""Upload duration constants.

DB timestamps (`created_at_unix`, leases, enqueue watermarks) are epoch
milliseconds from `storage.util.get_unix_timestamp`. boto3 `ExpiresIn` and SQS
`DelaySeconds` stay in seconds and are not converted here.
"""

POST_TTL_SECONDS = 1800
POST_TTL_MS = POST_TTL_SECONDS * 1000

LEASE_SECONDS = 15 * 60
LEASE_MS = LEASE_SECONDS * 1000

REENQUEUE_SECONDS = 15 * 60
REENQUEUE_MS = REENQUEUE_SECONDS * 1000

ABANDON_SECONDS = 40 * 60
ABANDON_MS = ABANDON_SECONDS * 1000

ACTIVE_RETENTION_SECONDS = 24 * 60 * 60
ACTIVE_RETENTION_MS = ACTIVE_RETENTION_SECONDS * 1000
