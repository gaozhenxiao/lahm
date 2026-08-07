#!/bin/bash
# 日常增量流水线：腾讯 qfq 增量下载 -> 增量回测 -> 今日信号 -> 补净值图
set -e
cd /home/ubuntu/lahm
source .venv/bin/activate
export PYTHONUNBUFFERED=1
mkdir -p logs

echo "[start] $(date '+%Y-%m-%dT%H:%M:%S') incremental pipeline" | tee -a logs/kline_backtest_pipeline.log

echo "[1/4] download qfq incremental" | tee -a logs/kline_backtest_pipeline.log
python -u scripts/download_daily_qfq_tencent.py \
  --universe hs300_csi500_csi1000 \
  --incremental --datalen 15 --interval 0.1 \
  > logs/download_qfq_incremental.out 2>&1
echo "[done-download] $(date '+%Y-%m-%dT%H:%M:%S') exit=$?" | tee -a logs/kline_backtest_pipeline.log

echo "[2/4] incremental backtest" | tee -a logs/kline_backtest_pipeline.log
# 3.6G RAM: single worker; lookback 180d + warmup 800d
python -u scripts/incremental_backtest_factors.py --workers 1 --lookback-days 180 --warmup-days 800 --plot \
  > logs/incremental_backtest.out 2>&1
echo "[done-incremental] $(date '+%Y-%m-%dT%H:%M:%S') exit=$?" | tee -a logs/kline_backtest_pipeline.log

echo "[3/4] recompute today signals" | tee -a logs/kline_backtest_pipeline.log
python -u scripts/recompute_factor_signals_today.py --write-mongo \
  > logs/recompute_signals_today.out 2>&1 || true
echo "[done-signals] $(date '+%Y-%m-%dT%H:%M:%S') exit=$?" | tee -a logs/kline_backtest_pipeline.log

echo "[4/4] ensure equity pngs" | tee -a logs/kline_backtest_pipeline.log
python -u /tmp/replot_equity.py >> logs/replot_equity.out 2>&1 || true
echo "[done-pipeline] $(date '+%Y-%m-%dT%H:%M:%S')" | tee -a logs/kline_backtest_pipeline.log