# 毛利率ROE中档横盘(持有50)（gross_dual_mid_hold50）

毛利率+ROE中档横盘突破，持有加长。

标签：`基本面` · `技术面` · `毛利率` · `ROE` · `横盘`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **质量底线**：ROE ≥ **9.00%**
3. **ROE 改善**：相对上一披露期上升 ≥ **0.25%**（百分点/小数按数据口径）
4. **利润率改善**：毛利率/净利率环比上升 ≥ **0.50%**
5. **图形·收窄后突破**：振幅 ≤ 20.00% 的横盘背景下，收盘 ≥ 昨日起算 **60** 日高，且 > MA20
6. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
7. **出场（任一触发）**：止损 **−12.00%**；持有满 **50** 个交易日

信号实现：`signal_gross_dual_base_break`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一腿

来源：`data/factors/gross_dual_mid_hold50_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sh.601100** |
| 开仓 | 2019-08-29，约 20.67 元 |
| 清仓 | 2019-11-15，约 28.1 元 |
| 单腿涨跌 | **35.95%** |
| 当日组合贡献 | NAV 4.49% |
| 出场备注 | hold_end；买入2019-08-29 成本价20.6703 |

**开仓信号备注**：毛利率ROE双改善横盘突破

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only gross_dual_mid_hold50 --limit 40
python scripts/run_new_factors.py --only gross_dual_mid_hold50 --limit 0
```

产物：`data/factors/gross_dual_mid_hold50_*`
