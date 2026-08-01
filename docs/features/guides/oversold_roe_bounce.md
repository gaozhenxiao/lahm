# 急跌ROE反弹（oversold_roe_bounce）

ROE质量闸门下，短期急跌后收盘站上MA20。

标签：`ROE` · `超卖` · `反弹`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **质量底线**：ROE ≥ **8.00%**
3. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
4. **回撤过滤**：近 20 日回撤 ≤ **−12.00%**（避免追高）
5. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
6. **出场（任一触发）**：止损 **−12.00%**；持有满 **15** 个交易日

信号实现：`signal_oversold_roe_bounce`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一腿

来源：`data/factors/oversold_roe_bounce_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sz.001280** |
| 开仓 | 2026-01-07，约 64.58 元 |
| 清仓 | 2026-01-28，约 97.62 元 |
| 单腿涨跌 | **51.16%** |
| 当日组合贡献 | NAV 6.39% |
| 出场备注 | hold_end；买入2026-01-07 成本价64.5758 |

**开仓信号备注**：急跌超卖+ROE质量站上MA20

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only oversold_roe_bounce --limit 40
python scripts/run_new_factors.py --only oversold_roe_bounce --limit 0
```

产物：`data/factors/oversold_roe_bounce_*`
