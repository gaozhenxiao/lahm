# EPS加速横盘突破（eps_accel_base_break）

EPS同比加速后横盘突破。

标签：`基本面` · `技术面` · `EPS` · `横盘`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **成长闸门**：净利/营收同比 ≥ **8.00%**
3. **增速加速**：同比相对上期再抬升 ≥ **5.00%**
4. **财务热窗**：上述财务事件发生后的 **25** 个交易日内才允许技术信号
5. **图形·收窄后突破**：振幅 ≤ 24.00% 的横盘背景下，收盘 ≥ 昨日起算 **60** 日高，且 > MA20
6. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
7. **出场（任一触发）**：止损 **−12.00%**；持有满 **25** 个交易日

信号实现：`signal_eps_accel_base_break`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一笔

来源：`data/factors/eps_accel_base_break_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sz.000725** |
| 开仓 | 2026-05-22，约 5.114 元 |
| 清仓 | 2026-06-29，约 7.95 元 |
| 单笔涨跌 | **55.46%** |
| 当日组合贡献 | NAV 6.93% |
| 出场备注 | hold_end；买入2026-05-22 成本价5.1139 |

**开仓信号备注**：EPS加速横盘突破

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only eps_accel_base_break --limit 40
python scripts/run_new_factors.py --only eps_accel_base_break --limit 0
```

产物：`data/factors/eps_accel_base_break_*`
