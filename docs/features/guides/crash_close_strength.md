# 急跌强收（crash_close_strength）

20日深度回撤后当日收阳并站上MA20。

标签：`另类` · `反转` · `日内强度`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
3. **回撤过滤**：近 20 日回撤 ≤ **−12.00%**（避免追高）
4. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
5. **出场（任一触发）**：止损 **−10.00%**；持有满 **10** 个交易日

信号实现：`signal_crash_close_strength`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一笔

来源：`data/factors/crash_close_strength_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sz.300476** |
| 开仓 | 2024-09-24，约 29.31 元 |
| 清仓 | 2024-10-15，约 42.12 元 |
| 单笔涨跌 | **43.69%** |
| 当日组合贡献 | NAV 5.46% |
| 出场备注 | hold_end；买入2024-09-24 成本价29.3109 |

**开仓信号备注**：急跌后强势收阳站上MA20

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only crash_close_strength --limit 40
python scripts/run_new_factors.py --only crash_close_strength --limit 0
```

产物：`data/factors/crash_close_strength_*`
