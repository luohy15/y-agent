#!/bin/bash
set -e

# Upsert or delete a Cloudflare DNS CNAME record
# Usage: ./scripts/upsert-dns.sh <subdomain> <cname-target> [DELETE]

SUBDOMAIN="${1:?Usage: upsert-dns.sh <subdomain> <cname-target> [DELETE]}"
CNAME_TARGET="${2:?Usage: upsert-dns.sh <subdomain> <cname-target> [DELETE]}"
ACTION="${3:-UPSERT}"  # UPSERT or DELETE

CLOUDFLARE_API_TOKEN="${CLOUDFLARE_API_TOKEN:?CLOUDFLARE_API_TOKEN env var required}"
CLOUDFLARE_ZONE_ID="${CLOUDFLARE_ZONE_ID:?CLOUDFLARE_ZONE_ID env var required}"
DOMAIN_NAME="${DOMAIN_NAME:-yovy.app}"
RECORD_NAME="${SUBDOMAIN}.${DOMAIN_NAME}"

CF_API="https://api.cloudflare.com/client/v4"
AUTH_HEADER="Authorization: Bearer ${CLOUDFLARE_API_TOKEN}"
CONTENT_TYPE="Content-Type: application/json"

# Find existing record
echo "Looking up DNS record: ${RECORD_NAME}"
EXISTING=$(curl -s -X GET \
    "${CF_API}/zones/${CLOUDFLARE_ZONE_ID}/dns_records?name=${RECORD_NAME}&type=CNAME" \
    -H "${AUTH_HEADER}" \
    -H "${CONTENT_TYPE}")

RECORD_ID=$(echo "$EXISTING" | jq -r '.result[0].id // empty')

if [ "$ACTION" = "DELETE" ]; then
    if [ -n "$RECORD_ID" ]; then
        echo "Deleting DNS record ${RECORD_NAME} (${RECORD_ID})..."
        curl -s -X DELETE \
            "${CF_API}/zones/${CLOUDFLARE_ZONE_ID}/dns_records/${RECORD_ID}" \
            -H "${AUTH_HEADER}" \
            -H "${CONTENT_TYPE}" | jq .
        echo "DNS record deleted."
    else
        echo "No DNS record found for ${RECORD_NAME}, nothing to delete."
    fi
else
    RECORD_DATA=$(jq -n \
        --arg name "$RECORD_NAME" \
        --arg content "$CNAME_TARGET" \
        '{type: "CNAME", name: $name, content: $content, ttl: 1, proxied: false}')

    if [ -n "$RECORD_ID" ]; then
        echo "Updating existing DNS record (${RECORD_ID})..."
        curl -s -X PUT \
            "${CF_API}/zones/${CLOUDFLARE_ZONE_ID}/dns_records/${RECORD_ID}" \
            -H "${AUTH_HEADER}" \
            -H "${CONTENT_TYPE}" \
            -d "$RECORD_DATA" | jq .
    else
        echo "Creating new DNS record..."
        curl -s -X POST \
            "${CF_API}/zones/${CLOUDFLARE_ZONE_ID}/dns_records" \
            -H "${AUTH_HEADER}" \
            -H "${CONTENT_TYPE}" \
            -d "$RECORD_DATA" | jq .
    fi
    echo "DNS record upserted: ${RECORD_NAME} -> ${CNAME_TARGET}"
fi
