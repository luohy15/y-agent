#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/../.github/config.json"

gh secret set CONFIG < "$CONFIG_FILE"
echo "CONFIG secret set from $CONFIG_FILE"
