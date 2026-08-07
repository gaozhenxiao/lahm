#!/bin/bash
set -e
cd /home/ubuntu/lahm
source .venv/bin/activate
export PYTHONUNBUFFERED=1
mkdir -p logs

echo "[start] $(date '+%Y-%m-%dT%H:%M:%S')" | tee -a logs/fill_missing_pipeline.log

# j66 codes incremental qfq
CODES=$(python - <<'PY'
import pandas as pd
print(','.join(pd.read_parquet('data/factors/_shared/universe_ind_j66.parquet')['code'].astype(str).tolist()))
PY
)
echo "[j66] downloading $(echo "$CODES" | tr ',' '\n' | wc -l) codes" | tee -a logs/fill_missing_pipeline.log
python -u scripts/download_daily_qfq_tencent.py \
  --universe hs300 \
  --force-codes "$CODES" \
  --incremental --datalen 20 --interval 0.08 \
  > logs/download_j66.out 2>&1
echo "[done-j66-download] $(date '+%Y-%m-%dT%H:%M:%S')" | tee -a logs/fill_missing_pipeline.log

python -u scripts/fill_missing_factor_backtests.py \
  > logs/fill_missing_backtests.out 2>&1
echo "[done-fill] $(date '+%Y-%m-%dT%H:%M:%S') exit=$?" | tee -a logs/fill_missing_pipeline.log
