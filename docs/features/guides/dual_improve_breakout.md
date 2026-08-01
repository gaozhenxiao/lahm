# 双改善突破（dual_improve_breakout）

ROE与净利率同时改善后突破60日高。

标签：`基本面` · `技术面` · `ROE` · `净利率`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **ROE 改善**：相对上一披露期上升 ≥ **0.20%**（百分点/小数按数据口径）
3. **利润率改善**：毛利率/净利率环比上升 ≥ **0.30%**
4. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
5. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
6. **出场（任一触发）**：止损 **−12.00%**；持有满 **25** 个交易日

信号实现：`signal_dual_improve_breakout`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一腿

来源：`data/factors/dual_improve_breakout_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sz.000408** |
| 开仓 | 2021-05-07，约 10.97 元 |
| 清仓 | 2021-06-11，约 17.25 元 |
| 单腿涨跌 | **57.21%** |
| 当日组合贡献 | NAV 7.15% |
| 出场备注 | hold_end；买入2021-05-07 成本价10.9718 |

**开仓信号备注**：ROE净利率双改善突破

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only dual_improve_breakout --limit 40
python scripts/run_new_factors.py --only dual_improve_breakout --limit 0
```

产物：`data/factors/dual_improve_breakout_*`
