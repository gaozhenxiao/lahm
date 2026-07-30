# 动量回踩（momentum_ma_pullback）

60日动量为正时，回撤后收盘站上MA20（图形确认）。

## 怎么跑

```bash
python scripts/run_new_factors.py --only momentum_ma_pullback --limit 40
python scripts/run_new_factors.py --only momentum_ma_pullback --limit 0
```

产物：`data/factors/momentum_ma_pullback_*`
