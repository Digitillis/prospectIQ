#!/usr/bin/env bash
# Runs repeated Apollo discovery passes until the target company count is reached.
# Usage: ./scripts/run_discovery_loop.sh [target] [parallel]
# Defaults: target=10000, parallel=4

TARGET=${1:-10000}
PARALLEL=${2:-4}
PYTHON=".venv/bin/python"
CAMPAIGN="prospectiq_discovery_batch3"
LOG_DIR="logs"
mkdir -p "$LOG_DIR"

# All active tiers (excludes watchlist: mfg6, pmfg2, pmfg5, pmfg6)
ALL_TIERS="mfg1,mfg2,mfg3,mfg8,mfg4,mfg5,mfg7,pmfg1,pmfg3,pmfg4,pmfg7,pmfg8,fb1,fb2,fb3,fb4"

get_company_count() {
  $PYTHON -c "
import os
os.environ['SUPABASE_URL'] = 'https://wlyhbdmjhgvovigogdco.supabase.co'
os.environ['SUPABASE_SERVICE_KEY'] = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6IndseWhiZG1qaGd2b3ZpZ29nZGNvIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2OTEzMDk3OSwiZXhwIjoyMDg0NzA2OTc5fQ.xjWmbOTlpXORqSe5wX7BiGNwjIBpPnRjP3rANs389gQ'
from supabase import create_client
sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
r = sb.table('companies').select('id', count='exact').execute()
print(r.count)
" 2>/dev/null
}

ROUND=0
while true; do
  COUNT=$(get_company_count)
  echo "[$(date '+%H:%M:%S')] Round $ROUND — Companies in DB: $COUNT / $TARGET"

  if [ "$COUNT" -ge "$TARGET" ]; then
    echo "Target of $TARGET reached! Final count: $COUNT"
    break
  fi

  REMAINING=$((TARGET - COUNT))
  echo "  Need ~$REMAINING more. Launching $PARALLEL parallel discovery passes..."

  PIDS=()
  for i in $(seq 1 $PARALLEL); do
    LOG="$LOG_DIR/discovery_loop_r${ROUND}_p${i}_$(date +%H%M%S).log"
    $PYTHON -m backend.app.agents.discovery \
      --campaign "$CAMPAIGN" \
      --tiers "$ALL_TIERS" \
      --max-pages 10 \
      > "$LOG" 2>&1 &
    PIDS+=($!)
    echo "  Pass $i started (PID $!)"
    sleep 2  # stagger starts slightly to avoid thundering herd on DB
  done

  # Wait for all parallel passes to finish
  for pid in "${PIDS[@]}"; do
    wait "$pid"
  done

  # Print round summary
  for i in $(seq 1 $PARALLEL); do
    LOG=$(ls "$LOG_DIR"/discovery_loop_r${ROUND}_p${i}_*.log 2>/dev/null | tail -1)
    if [ -f "$LOG" ]; then
      ADDED=$(grep "Processed:" "$LOG" | tail -1 | grep -oE 'Processed: [0-9]+' | grep -oE '[0-9]+')
      echo "  Pass $i: +${ADDED:-?} companies"
    fi
  done

  ROUND=$((ROUND + 1))
  sleep 5
done

NEW_COUNT=$(get_company_count)
echo ""
echo "Discovery loop complete. Final DB count: $NEW_COUNT"
