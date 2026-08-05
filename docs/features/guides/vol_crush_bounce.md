# 波动压缩反弹（vol_crush_bounce）

波动率从高位回落压缩后，价格站上MA20。

标签：`另类` · `波动率` · `体制切换`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
3. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
4. **出场（任一触发）**：止损 **−12.00%**；持有满 **15** 个交易日

信号实现：`signal_vol_crush_bounce`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一笔

来源：`data/factors/vol_crush_bounce_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sz.300122 智飞生物** |
| 开仓 | 2025-07-08，约 19.85 元 |
| 清仓 | 2025-07-29，约 25.06 元 |
| 单笔涨跌 | **26.25%** |
| 当日组合贡献 | NAV 3.28% |
| 出场备注 | hold_end；买入2025-07-08 成本价19.8500 |

**开仓信号备注**：波动压缩后站上MA20

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only vol_crush_bounce --limit 40
python scripts/run_new_factors.py --only vol_crush_bounce --limit 0
```

产物：`data/factors/vol_crush_bounce_*`
