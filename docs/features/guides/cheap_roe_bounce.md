# 低估高ROE急跌反弹（cheap_roe_bounce）

PE分位偏低且ROE达标，急跌后收盘站上MA20。

标签：`估值` · `ROE` · `反弹`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **估值闸门**：PE 历史分位 ≤ **35.00%**（窗口 `756` 交易日）
3. **质量底线**：ROE ≥ **10.00%**
4. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
5. **回撤过滤**：近 20 日回撤 ≤ **−8.00%**（避免追高）
6. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
7. **出场（任一触发）**：止损 **−12.00%**；持有满 **15** 个交易日

信号实现：`signal_cheap_roe_bounce`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一笔

来源：`data/factors/cheap_roe_bounce_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sz.002714** |
| 开仓 | 2021-01-18，约 53.87 元 |
| 清仓 | 2021-02-08，约 75.15 元 |
| 单笔涨跌 | **39.50%** |
| 当日组合贡献 | NAV 4.94% |
| 出场备注 | hold_end；买入2021-01-18 成本价53.8704 |

**开仓信号备注**：低估高ROE急跌后站上MA20

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only cheap_roe_bounce --limit 40
python scripts/run_new_factors.py --only cheap_roe_bounce --limit 0
```

产物：`data/factors/cheap_roe_bounce_*`
