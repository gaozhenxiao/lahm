# 毛净利差收敛（gross_net_catchup）

高毛利下净利率环比上升（经营杠杆改善）。

标签：`基本面` · `毛利率` · `净利率`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **利润率改善**：毛利率/净利率环比上升 ≥ **0.80%**
3. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
4. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
5. **出场（任一触发）**：止损 **−12.00%**；持有满 **25** 个交易日

信号实现：`signal_gross_net_catchup`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一腿

来源：`data/factors/gross_net_catchup_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sz.300033** |
| 开仓 | 2024-10-24，约 137 元 |
| 清仓 | 2024-11-28，约 212.7 元 |
| 单腿涨跌 | **55.26%** |
| 当日组合贡献 | NAV 6.91% |
| 出场备注 | hold_end；买入2024-10-24 成本价137.0162 |

**开仓信号备注**：高毛利下净利率追赶

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only gross_net_catchup --limit 40
python scripts/run_new_factors.py --only gross_net_catchup --limit 0
```

产物：`data/factors/gross_net_catchup_*`
