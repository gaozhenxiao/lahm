# 净利率扩张金叉（profit_margin_expand）

净利率环比扩张且估值不贵时均线金叉。

标签：`自研` · `净利率` · `金叉`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **估值闸门**：PE 历史分位 ≤ **70.00%**（窗口 `756` 交易日）
3. **利润率改善**：毛利率/净利率环比上升 ≥ **0.50%**
4. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
5. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
6. **出场（任一触发）**：止损 **−12.00%**；持有满 **25** 个交易日

信号实现：`signal_profit_margin_expand`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一笔

来源：`data/factors/profit_margin_expand_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sh.600460** |
| 开仓 | 2017-08-15，约 6.579 元 |
| 清仓 | 2017-09-19，约 8.056 元 |
| 单笔涨跌 | **22.46%** |
| 当日组合贡献 | NAV 2.81% |
| 出场备注 | hold_end；买入2017-08-15 成本价6.5786 |

**开仓信号备注**：净利率扩张金叉

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only profit_margin_expand --limit 40
python scripts/run_new_factors.py --only profit_margin_expand --limit 0
```

产物：`data/factors/profit_margin_expand_*`
