# 窄幅突破（narrow_range_breakout）

近端振幅处在低分位后，收盘创20日新高。

标签：`波动收敛` · `突破`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
3. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
4. **出场（任一触发）**：止损 **−12.00%**；持有满 **15** 个交易日

信号实现：`signal_narrow_range_breakout`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一腿

来源：`data/factors/narrow_range_breakout_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sz.000977** |
| 开仓 | 2023-01-19，约 23.55 元 |
| 清仓 | 2023-02-16，约 37.63 元 |
| 单腿涨跌 | **59.80%** |
| 当日组合贡献 | NAV 7.47% |
| 出场备注 | hold_end；买入2023-01-19 成本价23.5504 |

**开仓信号备注**：窄幅整理后向上突破

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only narrow_range_breakout --limit 40
python scripts/run_new_factors.py --only narrow_range_breakout --limit 0
```

产物：`data/factors/narrow_range_breakout_*`
