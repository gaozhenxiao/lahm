# 高净利率突破（high_margin_breakout）

高净利率且动量不差，突破60日高。

标签：`自研` · `净利率` · `突破`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **利润率水平**：毛利率（或规则指定利润率）≥ **12.00%**
3. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
4. **动量下限**：动量指标 ≥ **-2.00%**
5. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
6. **出场（任一触发）**：止损 **−12.00%**；持有满 **20** 个交易日

信号实现：`signal_high_margin_breakout`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一腿

来源：`data/factors/high_margin_breakout_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sz.300059** |
| 开仓 | 2024-09-26，约 13.99 元 |
| 清仓 | 2024-10-29，约 22.01 元 |
| 单腿涨跌 | **57.31%** |
| 当日组合贡献 | NAV 10.68% |
| 出场备注 | hold_end；买入2024-09-26 成本价13.9888 |

**开仓信号备注**：高净利率突破60日高

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only high_margin_breakout --limit 40
python scripts/run_new_factors.py --only high_margin_breakout --limit 0
```

产物：`data/factors/high_margin_breakout_*`
