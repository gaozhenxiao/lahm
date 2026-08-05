# 换手放大上均线（turn_surge_ma_reclaim）

换手相对20日均值明显放大，同时收盘站上MA60。

标签：`换手` · `资金` · `均线`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
3. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
4. **出场（任一触发）**：止损 **−12.00%**；持有满 **15** 个交易日

信号实现：`signal_turn_surge_ma_reclaim`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一笔

来源：`data/factors/turn_surge_ma_reclaim_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sz.000725** |
| 开仓 | 2019-02-11，约 2.411 元 |
| 清仓 | 2019-03-04，约 3.801 元 |
| 单笔涨跌 | **57.66%** |
| 当日组合贡献 | NAV 7.21% |
| 出场备注 | hold_end；买入2019-02-11 成本价2.4106 |

**开仓信号备注**：换手放大站上MA60

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only turn_surge_ma_reclaim --limit 40
python scripts/run_new_factors.py --only turn_surge_ma_reclaim --limit 0
```

产物：`data/factors/turn_surge_ma_reclaim_*`
