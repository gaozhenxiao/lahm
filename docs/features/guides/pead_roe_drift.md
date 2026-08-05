# ROE改善漂移（pead_roe_drift）

ROE改善披露后，数日内回踩MA20不破再买（简化PEAD）。

标签：`PEAD` · `ROE` · `财报后`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **ROE 改善**：相对上一披露期上升 ≥ **0.50%**（百分点/小数按数据口径）
3. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
4. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
5. **出场（任一触发）**：止损 **−12.00%**；持有满 **20** 个交易日

信号实现：`signal_pead_post_earn`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一笔

来源：`data/factors/pead_roe_drift_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sh.688183** |
| 开仓 | 2025-08-20，约 57.7 元 |
| 清仓 | 2025-09-17，约 90.7 元 |
| 单笔涨跌 | **57.18%** |
| 当日组合贡献 | NAV 7.15% |
| 出场备注 | hold_end；买入2025-08-20 成本价57.7034 |

**开仓信号备注**：ROE改善后回踩MA20确认

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only pead_roe_drift --limit 40
python scripts/run_new_factors.py --only pead_roe_drift --limit 0
```

产物：`data/factors/pead_roe_drift_*`
