# 双低估回踩（double_cheap_reclaim）

PE与PB同时处在偏低分位，收盘站上MA20。

## 怎么跑

```bash
python scripts/run_new_factors.py --only double_cheap_reclaim --limit 40
python scripts/run_new_factors.py --only double_cheap_reclaim --limit 0
```

产物：`data/factors/double_cheap_reclaim_*`
