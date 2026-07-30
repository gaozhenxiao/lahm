# 跳空修复（gap_down_recover）

明显跳空低开后，数日内收盘收复缺口并站上MA20。

## 怎么跑

```bash
python scripts/run_new_factors.py --only gap_down_recover --limit 40
python scripts/run_new_factors.py --only gap_down_recover --limit 0
```

产物：`data/factors/gap_down_recover_*`
