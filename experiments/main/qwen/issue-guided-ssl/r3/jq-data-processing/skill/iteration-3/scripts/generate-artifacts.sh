#!/usr/bin/env bash
# generate-artifacts.sh
# Generates the three required artifacts for a jq-data-processing task.
#
# Usage: ./generate-artifacts.sh <input.json> <output.json> "<jq_filter>"
#
# This script creates:
#   1. <output.json> - the transformed JSON output
#   2. /app/cmd.sh - the exact jq command
#   3. /app/jq_args.yaml - the YAML argument manifest

set -euo pipefail

INPUT_FILE="${1:?Usage: $0 <input.json> <output.json> \"<jq_filter>\"}"
OUTPUT_FILE="${2:?Usage: $0 <input.json> <output.json> \"<jq_filter>\"}"
JQ_FILTER="${3:?Usage: $0 <input.json> <output.json> \"<jq_filter>\"}"

# 1. Generate the output JSON
jq --indent 2 "$JQ_FILTER" "$INPUT_FILE" > "$OUTPUT_FILE"
echo "Generated $OUTPUT_FILE ($(jq 'length' "$OUTPUT_FILE") records)"

# 2. Generate cmd.sh
cat > /app/cmd.sh << CMDEOF
jq --indent 2 '${JQ_FILTER}' ${INPUT_FILE} > ${OUTPUT_FILE}
CMDEOF
chmod +x /app/cmd.sh
echo "Generated /app/cmd.sh"

# 3. Generate jq_args.yaml
# Use YAML block scalar for the filter to avoid escaping issues
cat > /app/jq_args.yaml << YAMLEOF
filter: |
  ${JQ_FILTER}
args:
  - "--indent"
  - "2"
YAMLEOF
echo "Generated /app/jq_args.yaml"

# 4. Verify reconstruction from YAML produces identical output
RECONSTRUCTED=$(jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" "$INPUT_FILE")
ORIGINAL=$(cat "$OUTPUT_FILE")
if [ "$RECONSTRUCTED" = "$ORIGINAL" ]; then
    echo "✓ Reconstruction verified: YAML-based command produces identical output"
else
    echo "✗ WARNING: Reconstruction mismatch!"
    exit 1
fi
