# 新高回踩（new_high_pullback）

创120日新高后出现回撤，再站上MA20。

标签：`新高` · `回踩` · `强势`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
3. **回撤过滤**：近 20 日回撤 ≤ **−4.00%**（避免追高）
4. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
5. **出场（任一触发）**：止损 **−12.00%**；持有满 **15** 个交易日

信号实现：`signal_new_high_pullback`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一腿

来源：`data/factors/new_high_pullback_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sh.601618** |
| 开仓 | 2021-08-23，约 3.467 元 |
| 清仓 | 2021-09-13，约 5.411 元 |
| 单腿涨跌 | **56.08%** |
| 当日组合贡献 | NAV 7.01% |
| 出场备注 | hold_end；买入2021-08-23 成本价3.4669 |

**开仓信号备注**：新高后回踩站上MA20

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only new_high_pullback --limit 40
python scripts/run_new_factors.py --only new_high_pullback --limit 0
```

产物：`data/factors/new_high_pullback_*`
