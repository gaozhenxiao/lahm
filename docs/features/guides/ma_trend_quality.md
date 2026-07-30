# 质量均线金叉（ma_trend_quality）

ROE不太差且估值不过贵时，MA20上穿MA60形成多头。

## 怎么跑

```bash
python scripts/run_new_factors.py --only ma_trend_quality --limit 40
python scripts/run_new_factors.py --only ma_trend_quality --limit 0
```

产物：`data/factors/ma_trend_quality_*`
