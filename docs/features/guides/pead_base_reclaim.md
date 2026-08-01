# 财报后横盘回踩（pead_base_reclaim）

财务改善公告后延迟确认，横盘中站上MA20。

标签：`基本面` · `技术面` · `PEAD` · `横盘`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **财务热窗**：上述财务事件发生后的 **20** 个交易日内才允许技术信号
3. **图形·收窄后突破**：振幅 ≤ 25.00% 的横盘背景下，收盘 ≥ 昨日起算 **60** 日高，且 > MA20
4. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
5. **出场（任一触发）**：止损 **−12.00%**；持有满 **25** 个交易日

信号实现：`signal_pead_base_reclaim`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一腿

来源：`data/factors/pead_base_reclaim_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sh.600160** |
| 开仓 | 2026-05-22，约 35.5 元 |
| 清仓 | 2026-06-29，约 53.8 元 |
| 单腿涨跌 | **51.54%** |
| 当日组合贡献 | NAV 6.44% |
| 出场备注 | hold_end；买入2026-05-22 成本价35.5028 |

**开仓信号备注**：财报改善后横盘回踩

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only pead_base_reclaim --limit 40
python scripts/run_new_factors.py --only pead_base_reclaim --limit 0
```

产物：`data/factors/pead_base_reclaim_*`
