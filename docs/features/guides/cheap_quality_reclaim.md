# 低估高质量回踩（cheap_quality_reclaim）

低PB高ROE，回踩站上MA20。

标签：`基本面` · `技术面` · `估值` · `质量`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **估值闸门**：PB 历史分位 ≤ **35.00%**（窗口 `756` 交易日）
3. **质量底线**：ROE ≥ **10.00%**
4. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
5. **回撤过滤**：近 20 日回撤 ≤ **−3.00%**（避免追高）
6. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
7. **出场（任一触发）**：止损 **−12.00%**；持有满 **25** 个交易日

信号实现：`signal_cheap_quality_reclaim`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一腿

来源：`data/factors/cheap_quality_reclaim_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sz.300033** |
| 开仓 | 2023-02-20，约 82.85 元 |
| 清仓 | 2023-03-27，约 131.4 元 |
| 单腿涨跌 | **58.66%** |
| 当日组合贡献 | NAV 7.33% |
| 出场备注 | hold_end；买入2023-02-20 成本价82.8496 |

**开仓信号备注**：低估高质量回踩

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only cheap_quality_reclaim --limit 40
python scripts/run_new_factors.py --only cheap_quality_reclaim --limit 0
```

产物：`data/factors/cheap_quality_reclaim_*`
