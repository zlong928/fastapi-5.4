#!/bin/bash

set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8000}"
UPLOAD_DIR="${2:-data/mock_uploads}"

for file in "$UPLOAD_DIR"/*; do
  [ -f "$file" ] || continue
  curl -sS -F "file=@${file}" "${BASE_URL}/upload" >/dev/null
done

curl -sS -X POST "${BASE_URL}/tasks/process-all" >/dev/null
echo "Uploaded files from $UPLOAD_DIR to $BASE_URL"

