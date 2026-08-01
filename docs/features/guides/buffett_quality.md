# 巴菲特质量回踩（buffett_quality）

高ROE+高净利率，估值不过贵时回踩站上MA60。

标签：`巴菲特` · `质量` · `ROE`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **估值闸门**：PE 历史分位 ≤ **65.00%**（窗口 `756` 交易日）
3. **质量底线**：ROE ≥ **15.00%**
4. **利润率水平**：毛利率（或规则指定利润率）≥ **12.00%**
5. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
6. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
7. **出场（任一触发）**：止损 **−12.00%**；持有满 **30** 个交易日

信号实现：`signal_buffett_quality`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一腿

来源：`data/factors/buffett_quality_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sz.300442** |
| 开仓 | 2025-12-09，约 50.05 元 |
| 清仓 | 2026-01-22，约 77.81 元 |
| 单腿涨跌 | **55.46%** |
| 当日组合贡献 | NAV 6.93% |
| 出场备注 | hold_end；买入2025-12-09 成本价50.0512 |

**开仓信号备注**：巴菲特质量回踩MA60

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only buffett_quality --limit 40
python scripts/run_new_factors.py --only buffett_quality --limit 0
```

产物：`data/factors/buffett_quality_*`
