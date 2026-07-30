# 低PB回踩确认（pb_low_ma_reclaim）

PB历史分位偏低时，等待收盘重新站上MA60，避免单纯抄底。

## 怎么跑

```bash
python scripts/run_new_factors.py --only pb_low_ma_reclaim --limit 40
python scripts/run_new_factors.py --only pb_low_ma_reclaim --limit 0
```

产物：`data/factors/pb_low_ma_reclaim_*`
