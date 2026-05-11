#!/bin/bash
# Smoke check for todo 2011 — Telegram-sourced messages must propagate
# chat.work_dir so the worker resumes the existing Claude Code session in
# its original cwd instead of starting a fresh one in the default VM dir.
#
# How it works:
#   1. Create a fresh chat with a non-default work_dir (default:
#      /Users/roy/luohy15/code/TradingAgents) via `y chat -m ... --work-dir ...`.
#   2. Wait briefly for the worker to register the process.
#   3. POST a fake Telegram webhook update targeting that chat
#      (using /<chat_id> routing).
#   4. Assert that the DynamoDB process row for the chat reports
#      work_dir == chat.work_dir (proves _handle_routed_message forwarded
#      the override) instead of falling back to the user's default VM dir.
#
# Usage:
#   scripts/smoke-telegram-resume.sh [<work_dir>]
#
# Requires:
#   - DATABASE_URL              (Postgres reachable from this host)
#   - TELEGRAM_WEBHOOK_SECRET   (matches the running API)
#   - API_BASE_URL              (default: http://localhost:8001)
#   - JWT                       (auth token for /api/chat — get via `y login`
#                                or copy from the web app)
#   - TELEGRAM_USER_ID          (the Telegram user_id bound to your account)
#
# This is a manual smoke (no test framework). Exit code 0 = pass.

set -euo pipefail

WORK_DIR="${1:-/Users/roy/luohy15/code/TradingAgents}"
API_BASE_URL="${API_BASE_URL:-http://localhost:8001}"
TELEGRAM_USER_ID="${TELEGRAM_USER_ID:-}"
JWT="${JWT:-}"
TELEGRAM_WEBHOOK_SECRET="${TELEGRAM_WEBHOOK_SECRET:-}"
DATABASE_URL="${DATABASE_URL:-}"

if [ -z "$JWT" ] || [ -z "$TELEGRAM_USER_ID" ] || [ -z "$TELEGRAM_WEBHOOK_SECRET" ] || [ -z "$DATABASE_URL" ]; then
  echo "ERROR: set JWT, TELEGRAM_USER_ID, TELEGRAM_WEBHOOK_SECRET, DATABASE_URL" >&2
  exit 1
fi

echo "[1/4] Creating chat with work_dir=$WORK_DIR"
CREATE_RESP=$(curl -sS -X POST "$API_BASE_URL/api/chat" \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d "{\"prompt\": \"smoke: pwd && echo SMOKE_OK\", \"work_dir\": \"$WORK_DIR\"}")
CHAT_ID=$(echo "$CREATE_RESP" | python3 -c 'import sys,json; print(json.load(sys.stdin)["chat_id"])')
echo "    chat_id=$CHAT_ID"

echo "[2/4] Waiting 8s for worker to register the detached process..."
sleep 8

echo "[3/4] POST fake Telegram webhook routed to /$CHAT_ID"
TG_PAYLOAD=$(cat <<EOF
{
  "update_id": 1,
  "message": {
    "message_id": 1,
    "from": {"id": $TELEGRAM_USER_ID, "is_bot": false, "first_name": "smoke"},
    "chat": {"id": $TELEGRAM_USER_ID, "type": "private"},
    "date": $(date +%s),
    "text": "/$CHAT_ID smoke followup"
  }
}
EOF
)
TG_RESP=$(curl -sS -X POST "$API_BASE_URL/api/telegram/webhook" \
  -H "Content-Type: application/json" \
  -H "X-Telegram-Bot-Api-Secret-Token: $TELEGRAM_WEBHOOK_SECRET" \
  -d "$TG_PAYLOAD")
echo "    webhook response: $TG_RESP"

echo "[4/4] Asserting process work_dir matches chat.work_dir"
sleep 5

# Pull chat.work_dir from Postgres (json_content) and the process's
# registered work_dir from DynamoDB.
CHAT_WORK_DIR=$(python3 - "$DATABASE_URL" "$CHAT_ID" <<'PY'
import sys, json
import psycopg
dsn = sys.argv[1].replace("postgresql+psycopg://", "postgresql://")
chat_id = sys.argv[2]
with psycopg.connect(dsn) as conn, conn.cursor() as cur:
    cur.execute("SELECT json_content FROM chat WHERE chat_id=%s", (chat_id,))
    row = cur.fetchone()
    if not row:
        print("NOT_FOUND")
        sys.exit(2)
    print(json.loads(row[0]).get("work_dir") or "")
PY
)

PROC_WORK_DIR=$(python3 - "$CHAT_ID" <<'PY'
import sys, boto3, os
table = os.environ.get("PROCESS_TABLE", "y-agent-processes")
chat_id = sys.argv[1]
ddb = boto3.client("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
resp = ddb.get_item(TableName=table, Key={"chat_id": {"S": chat_id}})
item = resp.get("Item") or {}
print(item.get("work_dir", {}).get("S", ""))
PY
)

echo "    chat.work_dir   = $CHAT_WORK_DIR"
echo "    process.work_dir = $PROC_WORK_DIR"

if [ -z "$CHAT_WORK_DIR" ] || [ "$CHAT_WORK_DIR" != "$PROC_WORK_DIR" ]; then
  echo "FAIL: work_dir mismatch — Telegram path did not propagate chat.work_dir" >&2
  exit 1
fi

echo "PASS: Telegram-sourced message kept work_dir=$CHAT_WORK_DIR"
