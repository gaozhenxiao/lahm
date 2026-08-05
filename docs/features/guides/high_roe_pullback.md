# 高ROE回踩（high_roe_pullback）

高ROE且估值不过贵，回踩站上MA60。

标签：`自研` · `ROE` · `回踩`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **估值闸门**：PE 历史分位 ≤ **60.00%**（窗口 `756` 交易日）
3. **质量底线**：ROE ≥ **15.00%**
4. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
5. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
6. **出场（任一触发）**：止损 **−12.00%**；持有满 **25** 个交易日

信号实现：`signal_high_roe_pullback`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一笔

来源：`data/factors/high_roe_pullback_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sz.002709** |
| 开仓 | 2021-04-19，约 27.2 元 |
| 清仓 | 2021-05-27，约 38.2 元 |
| 单笔涨跌 | **40.44%** |
| 当日组合贡献 | NAV 5.05% |
| 出场备注 | hold_end；买入2021-04-19 成本价27.2019 |

**开仓信号备注**：高ROE回踩MA60

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only high_roe_pullback --limit 40
python scripts/run_new_factors.py --only high_roe_pullback --limit 0
```

产物：`data/factors/high_roe_pullback_*`
