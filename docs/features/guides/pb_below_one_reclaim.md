# 破净回踩（pb_below_one_reclaim）

PB小于1时，收盘站上MA20再买。

标签：`破净` · `PB` · `均线`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **估值闸门**：PB 绝对值 ≤ **1**
3. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
4. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
5. **出场（任一触发）**：止损 **−12.00%**；持有满 **20** 个交易日

信号实现：`signal_pb_below_one_reclaim`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一笔

来源：`data/factors/pb_below_one_reclaim_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sz.000617** |
| 开仓 | 2024-09-20，约 4.973 元 |
| 清仓 | 2024-10-25，约 7.906 元 |
| 单笔涨跌 | **58.98%** |
| 当日组合贡献 | NAV 7.37% |
| 出场备注 | hold_end；买入2024-09-20 成本价4.9731 |

**开仓信号备注**：破净后站上MA20

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only pb_below_one_reclaim --limit 40
python scripts/run_new_factors.py --only pb_below_one_reclaim --limit 0
```

产物：`data/factors/pb_below_one_reclaim_*`
