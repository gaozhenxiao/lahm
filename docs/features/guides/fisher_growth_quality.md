# 费雪成长质量（fisher_growth_quality）

高增长+高净利率下突破60日高点。

标签：`费雪` · `成长` · `质量`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **利润率水平**：毛利率（或规则指定利润率）≥ **10.00%**
3. **成长闸门**：净利/营收同比 ≥ **25.00%**
4. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
5. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
6. **出场（任一触发）**：止损 **−15.00%**；持有满 **20** 个交易日

信号实现：`signal_fisher_growth_quality`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一笔

来源：`data/factors/fisher_growth_quality_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sz.300251** |
| 开仓 | 2025-02-10，约 16.37 元 |
| 清仓 | 2025-03-06，约 23.59 元 |
| 单笔涨跌 | **44.06%** |
| 当日组合贡献 | NAV 9.84% |
| 出场备注 | hold_end；买入2025-02-10 成本价16.3720 |

**开仓信号备注**：费雪成长质量突破

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only fisher_growth_quality --limit 40
python scripts/run_new_factors.py --only fisher_growth_quality --limit 0
```

产物：`data/factors/fisher_growth_quality_*`
