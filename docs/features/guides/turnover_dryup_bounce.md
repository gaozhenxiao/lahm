# 地量反弹（turnover_dryup_bounce）

换手先萎缩再放量，同时收盘站上MA20。

## 怎么跑

```bash
python scripts/run_new_factors.py --only turnover_dryup_bounce --limit 40
python scripts/run_new_factors.py --only turnover_dryup_bounce --limit 0
```

产物：`data/factors/turnover_dryup_bounce_*`
