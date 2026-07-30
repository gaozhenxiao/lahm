# 低波动回踩（low_vol_reclaim）

自身波动处在低分位时，回踩后收盘站上MA20（偏防守）。

## 怎么跑

```bash
python scripts/run_new_factors.py --only low_vol_reclaim --limit 40
python scripts/run_new_factors.py --only low_vol_reclaim --limit 0
```

产物：`data/factors/low_vol_reclaim_*`
