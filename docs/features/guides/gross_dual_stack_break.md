# 毛利率ROE双改善突破（gross_dual_stack_break）

毛利率与ROE同时改善后突破60日高。

标签：`基本面` · `技术面` · `毛利率` · `ROE`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **质量底线**：ROE ≥ **8.00%**
3. **ROE 改善**：相对上一披露期上升 ≥ **0.20%**（百分点/小数按数据口径）
4. **利润率改善**：毛利率/净利率环比上升 ≥ **0.40%**
5. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
6. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
7. **出场（任一触发）**：止损 **−12.00%**；持有满 **25** 个交易日

信号实现：`signal_gross_dual_stack_break`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一笔

来源：`data/factors/gross_dual_stack_break_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sz.000988** |
| 开仓 | 2023-03-01，约 20.71 元 |
| 清仓 | 2023-04-06，约 31.48 元 |
| 单笔涨跌 | **52.00%** |
| 当日组合贡献 | NAV 6.50% |
| 出场备注 | hold_end；买入2023-03-01 成本价20.7116 |

**开仓信号备注**：毛利率ROE双改善突破

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only gross_dual_stack_break --limit 40
python scripts/run_new_factors.py --only gross_dual_stack_break --limit 0
```

产物：`data/factors/gross_dual_stack_break_*`
