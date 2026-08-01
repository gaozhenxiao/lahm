# 布林下轨反弹（boll_lower_reclaim）

价格触及布林下轨附近后，收盘站上MA20。

标签：`布林` · `超卖` · `反弹`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
3. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
4. **出场（任一触发）**：止损 **−10.00%**；持有满 **12** 个交易日

信号实现：`signal_boll_lower_reclaim`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一腿

来源：`data/factors/boll_lower_reclaim_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sh.601058** |
| 开仓 | 2020-12-28，约 5.004 元 |
| 清仓 | 2021-01-14，约 7.874 元 |
| 单腿涨跌 | **57.35%** |
| 当日组合贡献 | NAV 7.17% |
| 出场备注 | hold_end；买入2020-12-28 成本价5.0041 |

**开仓信号备注**：触及布林下轨后站上MA20

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only boll_lower_reclaim --limit 40
python scripts/run_new_factors.py --only boll_lower_reclaim --limit 0
```

产物：`data/factors/boll_lower_reclaim_*`
