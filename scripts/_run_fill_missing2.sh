#!/bin/bash
set -e
cd /home/ubuntu/lahm
source .venv/bin/activate
export PYTHONUNBUFFERED=1
mkdir -p logs
echo "[start2] $(date '+%Y-%m-%dT%H:%M:%S')" | tee -a logs/fill_missing_pipeline.log
python -u scripts/fill_missing_factor_backtests.py --only bank > logs/fill_missing_backtests.out 2>&1
echo "[done-bank] $(date '+%Y-%m-%dT%H:%M:%S')" | tee -a logs/fill_missing_pipeline.log
python -u scripts/fill_missing_factor_backtests.py --only builtins --builtins-skip-run >> logs/fill_missing_backtests.out 2>&1
echo "[done-builtins-sync] $(date '+%Y-%m-%dT%H:%M:%S')" | tee -a logs/fill_missing_pipeline.log
python -u scripts/fill_missing_factor_backtests.py --only builtins >> logs/fill_missing_backtests.out 2>&1 || true
echo "[done-all] $(date '+%Y-%m-%dT%H:%M:%S')" | tee -a logs/fill_missing_pipeline.log
