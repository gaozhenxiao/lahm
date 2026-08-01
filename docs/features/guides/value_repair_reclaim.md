# 低估价值修复（value_repair_reclaim）

低估值叠加财务改善，站上MA60。

标签：`基本面` · `技术面` · `价值修复`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **估值闸门**：PE 历史分位 ≤ **30.00%**（窗口 `756` 交易日）
3. **财务热窗**：上述财务事件发生后的 **30** 个交易日内才允许技术信号
4. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
5. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
6. **出场（任一触发）**：止损 **−12.00%**；持有满 **30** 个交易日

信号实现：`signal_value_repair_reclaim`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一腿

来源：`data/factors/value_repair_reclaim_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sz.002050** |
| 开仓 | 2022-05-30，约 15.94 元 |
| 清仓 | 2022-07-12，约 25.23 元 |
| 单腿涨跌 | **58.26%** |
| 当日组合贡献 | NAV 7.28% |
| 出场备注 | hold_end；买入2022-05-30 成本价15.9391 |

**开仓信号备注**：低估价值修复站上MA60

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only value_repair_reclaim --limit 40
python scripts/run_new_factors.py --only value_repair_reclaim --limit 0
```

产物：`data/factors/value_repair_reclaim_*`
