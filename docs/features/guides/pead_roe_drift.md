# ROE改善漂移（pead_roe_drift）

ROE改善披露后，数日内回踩MA20不破再买（简化PEAD）。

## 怎么跑

```bash
python scripts/run_new_factors.py --only pead_roe_drift --limit 40
python scripts/run_new_factors.py --only pead_roe_drift --limit 0
```

产物：`data/factors/pead_roe_drift_*`
