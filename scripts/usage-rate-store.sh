#!/bin/bash
# Precompute the CRS run-rate reading and store it for GET /api/usage/rate to
# read, instead of that endpoint SSH-execing the CLI per request (todo 3121).
# Runs every minute via crontab, same style as auto-hibernate.sh: only runs
# while the VM is up, which is exactly when a live run rate exists — a
# VM-asleep period simply stops writing and the stored reading ages into the
# API's `stale: true` state on its own.

set -euo pipefail

y usage rate --store --json
