#!/bin/bash

set -euo pipefail

OUT_DIR="${1:-data/mock_uploads}"
COUNT="${2:-5}"

mkdir -p "$OUT_DIR"

for i in $(seq 1 "$COUNT"); do
  cat > "$OUT_DIR/sample_$i.txt" <<EOF
INFO sample file $i
WARN sample warning $i
ERROR sample error $i
EOF
  cat > "$OUT_DIR/sample_$i.log" <<EOF
2026-05-04 INFO sample log $i
2026-05-04 WARN sample log $i
2026-05-04 ERROR sample log $i
EOF
  cat > "$OUT_DIR/sample_$i.csv" <<EOF
name,status,detail
sample_$i,INFO,ok
sample_$i,WARN,notice
sample_$i,ERROR,failed
EOF
done

echo "Generated $COUNT file sets in $OUT_DIR"

