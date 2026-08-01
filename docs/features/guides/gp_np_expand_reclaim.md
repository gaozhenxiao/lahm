# 毛净利率双扩张回踩（gp_np_expand_reclaim）

毛利率与净利率同时扩张后，回踩站上MA20。

标签：`基本面` · `技术面` · `毛利率` · `净利率`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **利润率改善**：毛利率/净利率环比上升 ≥ **0.30%**
3. **净利率改善**：环比上升 ≥ **0.30%**
4. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
5. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
6. **出场（任一触发）**：止损 **−12.00%**；持有满 **25** 个交易日

信号实现：`signal_gp_np_expand_reclaim`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一腿

来源：`data/factors/gp_np_expand_reclaim_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sh.600196** |
| 开仓 | 2017-09-07，约 27.38 元 |
| 清仓 | 2017-10-19，约 35.58 元 |
| 单腿涨跌 | **29.93%** |
| 当日组合贡献 | NAV 3.74% |
| 出场备注 | hold_end；买入2017-09-07 成本价27.3808 |

**开仓信号备注**：毛净利率双扩张回踩

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only gp_np_expand_reclaim --limit 40
python scripts/run_new_factors.py --only gp_np_expand_reclaim --limit 0
```

产物：`data/factors/gp_np_expand_reclaim_*`
