# 价值动量组合（oshaughnessy_value_mom）

PE/PB双低估且60日动量为正，站上MA20。

标签：`奥肖内西` · `价值` · `动量`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **估值闸门**：PB 历史分位 ≤ **40.00%**（窗口 `756` 交易日）
3. **估值闸门**：PE 历史分位 ≤ **40.00%**（窗口 `756` 交易日）
4. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
5. **动量下限**：动量指标 ≥ **0.00%**
6. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
7. **出场（任一触发）**：止损 **−12.00%**；持有满 **20** 个交易日

信号实现：`signal_oshaughnessy_value_mom`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一笔

来源：`data/factors/oshaughnessy_value_mom_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sh.600893** |
| 开仓 | 2020-07-01，约 23.36 元 |
| 清仓 | 2020-07-29，约 37.36 元 |
| 单笔涨跌 | **59.92%** |
| 当日组合贡献 | NAV 7.49% |
| 出场备注 | hold_end；买入2020-07-01 成本价23.3597 |

**开仓信号备注**：价值+动量组合

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only oshaughnessy_value_mom --limit 40
python scripts/run_new_factors.py --only oshaughnessy_value_mom --limit 0
```

产物：`data/factors/oshaughnessy_value_mom_*`
