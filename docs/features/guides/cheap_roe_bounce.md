# 低估ROE反弹（cheap_roe_bounce）

PE分位偏低且ROE较高，急跌后收盘站上MA20再介入。

## 怎么跑

```bash
python scripts/run_new_factors.py --only cheap_roe_bounce --limit 40
python scripts/run_new_factors.py --only cheap_roe_bounce --limit 0
```

产物：`data/factors/cheap_roe_bounce_*`
