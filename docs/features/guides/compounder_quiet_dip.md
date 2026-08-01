# 安静复利回踩（compounder_quiet_dip）

高净利率+低波动，温和回撤后站上MA20。

标签：`另类` · `防御` · `复利`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **利润率水平**：毛利率（或规则指定利润率）≥ **12.00%**
3. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
4. **回撤过滤**：近 20 日回撤 ≤ **−3.00%**（避免追高）
5. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
6. **出场（任一触发）**：止损 **−10.00%**；持有满 **20** 个交易日

信号实现：`signal_compounder_quiet_dip`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一腿

来源：`data/factors/compounder_quiet_dip_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sz.000617** |
| 开仓 | 2024-09-20，约 4.973 元 |
| 清仓 | 2024-10-25，约 7.906 元 |
| 单腿涨跌 | **58.98%** |
| 当日组合贡献 | NAV 7.37% |
| 出场备注 | hold_end；买入2024-09-20 成本价4.9731 |

**开仓信号备注**：安静复利股回踩

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only compounder_quiet_dip --limit 40
python scripts/run_new_factors.py --only compounder_quiet_dip --limit 0
```

产物：`data/factors/compounder_quiet_dip_*`
