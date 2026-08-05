# ROE扩张突破(门槛0.12持有51)（roe_expand_r12_hold51）

更高ROE门槛 + 持有51。

标签：`基本面` · `技术面` · `ROE`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **质量底线**：ROE ≥ **12.00%**
3. **ROE 改善**：相对上一披露期上升 ≥ **0.30%**（百分点/小数按数据口径）
4. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
5. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
6. **出场（任一触发）**：止损 **−12.00%**；持有满 **51** 个交易日

信号实现：`signal_roe_expand_breakout`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一笔

来源：`data/factors/roe_expand_r12_hold51_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sz.002304** |
| 开仓 | 2020-10-22，约 135.2 元 |
| 清仓 | 2021-01-04，约 198.9 元 |
| 单笔涨跌 | **47.17%** |
| 当日组合贡献 | NAV 5.90% |
| 出场备注 | hold_end；买入2020-10-22 成本价135.1795 |

**开仓信号备注**：ROE扩张突破

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only roe_expand_r12_hold51 --limit 40
python scripts/run_new_factors.py --only roe_expand_r12_hold51 --limit 0
```

产物：`data/factors/roe_expand_r12_hold51_*`
