#!/usr/bin/env bash
# run_pipeline_loop.sh — Targeted full pipeline loop
#
# Wave 1 research: primary discrete + process mfg tiers only (~2,500 companies, ~$34)
# Skips F&B (fb1-fb4) and electronics (mfg4, mfg5) — those are wave 2.
#
# Qualification and enrichment run continuously on whatever is ready.
#
# Stop all: pkill -f 'run_pipeline_loop\|run_research\|run_qualification\|run_enrichment'

set -euo pipefail

PYTHON=".venv/bin/python"
LOG_DIR="logs/pipeline"
mkdir -p "$LOG_DIR"

echo "========================================"
echo " ProspectIQ Pipeline — Wave 1"
echo " Tiers: mfg1,mfg2,mfg3,mfg7,mfg8 + pmfg1,pmfg3,pmfg4"
echo " Est. companies: ~2,500 | Est. cost: ~\$34"
echo " Started: $(date)"
echo "========================================"

# ── Research shard function ──────────────────────────────────────────────────
research_shard() {
  local NAME="$1"
  local TIERS="$2"
  local LOG="$LOG_DIR/research_${NAME}.log"
  local ROUND=0

  echo "[Research/$NAME] Starting | tiers=$TIERS" | tee -a "$LOG"
  while true; do
    ROUND=$((ROUND + 1))
    echo "[$(date '+%H:%M:%S')][Research/$NAME] Round $ROUND" | tee -a "$LOG"

    OUT=$($PYTHON run_research.py --tiers $TIERS --limit 200 2>&1)
    echo "$OUT" >> "$LOG"

    # If nothing left to research in these tiers, pause longer
    if echo "$OUT" | grep -q "No companies to research"; then
      echo "[Research/$NAME] Queue empty — waiting 5min before retry" | tee -a "$LOG"
      sleep 300
    else
      sleep 10
    fi
  done
}

# ── Qualification loop ───────────────────────────────────────────────────────
qualification_loop() {
  local LOG="$LOG_DIR/qualification.log"
  local ROUND=0

  echo "[Qualification] Starting" | tee -a "$LOG"
  while true; do
    ROUND=$((ROUND + 1))
    echo "[$(date '+%H:%M:%S')][Qualification] Round $ROUND" | tee -a "$LOG"
    $PYTHON -m backend.scripts.run_qualification --limit 300 >> "$LOG" 2>&1 || true
    sleep 15
  done
}

# ── Enrichment loop ──────────────────────────────────────────────────────────
enrichment_loop() {
  local LOG="$LOG_DIR/enrichment.log"
  local ROUND=0

  echo "[Enrichment] Starting" | tee -a "$LOG"
  while true; do
    ROUND=$((ROUND + 1))
    echo "[$(date '+%H:%M:%S')][Enrichment] Round $ROUND" | tee -a "$LOG"
    $PYTHON -m backend.scripts.run_enrichment --limit 30 >> "$LOG" 2>&1 || true
    sleep 60
  done
}

# ── Launch shards ────────────────────────────────────────────────────────────

# Shard A: Core discrete manufacturing (mfg1=machinery, mfg2=fabrication, mfg3=auto)
research_shard "A_discrete" "mfg1 mfg2 mfg3" &
PID_A=$!

# Shard B: Metals + plastics + chemicals
research_shard "B_metals_chem" "mfg7 mfg8 pmfg1" &
PID_B=$!

# Shard C: Process manufacturing (refining + mining)
research_shard "C_process" "pmfg3 pmfg4" &
PID_C=$!

# Qualification
qualification_loop &
PID_Q=$!

# Enrichment
enrichment_loop &
PID_E=$!

echo ""
echo "Pipeline running:"
echo "  Research A (mfg1,mfg2,mfg3):   PID=$PID_A"
echo "  Research B (mfg7,mfg8,pmfg1):  PID=$PID_B"
echo "  Research C (pmfg3,pmfg4):       PID=$PID_C"
echo "  Qualification:                   PID=$PID_Q"
echo "  Enrichment:                      PID=$PID_E"
echo ""
echo "Monitor: tail -f logs/pipeline/*.log"
echo "Stop:    pkill -f 'run_pipeline_loop\|run_research\|run_qualification\|run_enrichment'"
echo ""

wait
