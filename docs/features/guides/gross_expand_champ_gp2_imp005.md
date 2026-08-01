# 毛利率连续扩张(改善0.005)（gross_expand_champ_gp2_imp005）

连续毛利改善 × imp005。

标签：`基本面` · `技术面` · `毛利率`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **利润率改善**：毛利率/净利率环比上升 ≥ **0.50%**
3. **利润率水平**：毛利率（或规则指定利润率）≥ **17.00%**
4. **净利率过滤**：净利率 ≥ **10.00%**
5. **连续改善**：毛利率连续两期环比上升（非单季脉冲）
6. **财务热窗**：上述财务事件发生后的 **29** 个交易日内才允许技术信号
7. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
8. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
9. **出场（任一触发）**：止损 **−12.00%**；持有满 **51** 个交易日

信号实现：`signal_gross_expand_break`（`app/services/factors/signal_specs.py`）。

## 怎么跑

```bash
python scripts/run_new_factors.py --only gross_expand_champ_gp2_imp005 --limit 40
python scripts/run_new_factors.py --only gross_expand_champ_gp2_imp005 --limit 0
```

产物：`data/factors/gross_expand_champ_gp2_imp005_*`
