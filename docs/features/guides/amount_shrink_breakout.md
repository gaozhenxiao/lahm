# 缩量后放量突破（amount_shrink_breakout）

成交额先萎缩再放量，同时收盘突破20日高点。

标签：`缩量` · `放量` · `突破`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
3. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
4. **出场（任一触发）**：止损 **−12.00%**；持有满 **12** 个交易日

信号实现：`signal_amount_shrink_breakout`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一笔

来源：`data/factors/amount_shrink_breakout_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sz.000999** |
| 开仓 | 2021-12-20，约 14.06 元 |
| 清仓 | 2022-01-06，约 20.51 元 |
| 单笔涨跌 | **45.80%** |
| 当日组合贡献 | NAV 5.72% |
| 出场备注 | hold_end；买入2021-12-20 成本价14.0639 |

**开仓信号备注**：缩量后放量突破20日高

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only amount_shrink_breakout --limit 40
python scripts/run_new_factors.py --only amount_shrink_breakout --limit 0
```

产物：`data/factors/amount_shrink_breakout_*`
