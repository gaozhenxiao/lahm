# 连续毛利×趋势回踩（gp_consec_pullback）

毛利率连续扩张热窗口内趋势回踩。

标签：`基本面` · `技术面` · `回踩` · `毛利率`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **利润率改善**：毛利率/净利率环比上升 ≥ **0.30%**
3. **利润率水平**：毛利率（或规则指定利润率）≥ **15.00%**
4. **净利率过滤**：净利率 ≥ **8.00%**
5. **连续改善**：毛利率连续两期环比上升（非单季脉冲）
6. **财务热窗**：上述财务事件发生后的 **30** 个交易日内才允许技术信号
7. **图形·趋势回踩**：MA60 上行；近 20 日回撤 ≥ **3.00%**；收盘重新站上 MA20 且仍在 MA60 上方
8. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
9. **出场（任一触发）**：止损 **−12.00%**；持有满 **35** 个交易日

信号实现：`signal_gp_consec_break`（`app/services/factors/signal_specs.py`）。

## 怎么跑

```bash
python scripts/run_new_factors.py --only gp_consec_pullback --limit 40
python scripts/run_new_factors.py --only gp_consec_pullback --limit 0
```

产物：`data/factors/gp_consec_pullback_*`
