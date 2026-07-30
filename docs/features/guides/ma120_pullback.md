# 长线多头回踩（ma120_pullback）

收盘与MA20均在MA120之上时，回踩站上MA20。

## 怎么跑

```bash
python scripts/run_new_factors.py --only ma120_pullback --limit 40
python scripts/run_new_factors.py --only ma120_pullback --limit 0
```

产物：`data/factors/ma120_pullback_*`
