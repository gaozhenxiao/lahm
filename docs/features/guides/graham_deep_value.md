# 格雷厄姆深价值（graham_deep_value）

PE/PB历史分位极低且盈利为正，收盘站上MA20。

标签：`格雷厄姆` · `价值` · `PB` · `PE`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **估值闸门**：PB 历史分位 ≤ **15.00%**（窗口 `756` 交易日）
3. **估值闸门**：PE 历史分位 ≤ **25.00%**（窗口 `756` 交易日）
4. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
5. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
6. **出场（任一触发）**：止损 **−12.00%**；持有满 **25** 个交易日

信号实现：`signal_graham_deep_value`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一腿

来源：`data/factors/graham_deep_value_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sz.002384** |
| 开仓 | 2019-01-25，约 9.937 元 |
| 清仓 | 2019-03-08，约 15.79 元 |
| 单腿涨跌 | **58.94%** |
| 当日组合贡献 | NAV 7.37% |
| 出场备注 | hold_end；买入2019-01-25 成本价9.9371 |

**开仓信号备注**：格雷厄姆深价值站上MA20

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only graham_deep_value --limit 40
python scripts/run_new_factors.py --only graham_deep_value --limit 0
```

产物：`data/factors/graham_deep_value_*`
