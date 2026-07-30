# 高利润率回踩（high_margin_pullback）

净利率较高且动量为正时，回踩后站上MA20。

## 怎么跑

```bash
python scripts/run_new_factors.py --only high_margin_pullback --limit 40
python scripts/run_new_factors.py --only high_margin_pullback --limit 0
```

产物：`data/factors/high_margin_pullback_*`
