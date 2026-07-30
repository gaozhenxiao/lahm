# 增长站上均线（eps_growth_reclaim）

盈利正增长且估值不过贵时，收盘站上MA60。

## 怎么跑

```bash
python scripts/run_new_factors.py --only eps_growth_reclaim --limit 40
python scripts/run_new_factors.py --only eps_growth_reclaim --limit 0
```

产物：`data/factors/eps_growth_reclaim_*`
