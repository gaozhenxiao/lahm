# 低PE回踩确认（pe_low_ma_reclaim）

PE历史分位偏低时，收盘站上MA60再介入。

## 怎么跑

```bash
python scripts/run_new_factors.py --only pe_low_ma_reclaim --limit 40
python scripts/run_new_factors.py --only pe_low_ma_reclaim --limit 0
```

产物：`data/factors/pe_low_ma_reclaim_*`
