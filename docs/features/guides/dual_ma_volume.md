# 放量金叉（dual_ma_volume）

MA20上穿MA60且成交额放大。

标签：`金叉` · `放量` · `趋势`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
3. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
4. **出场（任一触发）**：止损 **−12.00%**；持有满 **20** 个交易日

信号实现：`signal_dual_ma_volume`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一笔

来源：`data/factors/dual_ma_volume_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sh.601336** |
| 开仓 | 2024-09-03，约 31.18 元 |
| 清仓 | 2024-10-10，约 49.1 元 |
| 单笔涨跌 | **57.47%** |
| 当日组合贡献 | NAV 7.18% |
| 出场备注 | hold_end；买入2024-09-03 成本价31.1826 |

**开仓信号备注**：均线金叉且放量

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only dual_ma_volume --limit 40
python scripts/run_new_factors.py --only dual_ma_volume --limit 0
```

产物：`data/factors/dual_ma_volume_*`
