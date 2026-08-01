# ROE改善低PB（roe_improve_pb_cheap）

ROE环比改善且PB分位偏低，站上MA20。

标签：`自研` · `ROE` · `PB`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **估值闸门**：PB 历史分位 ≤ **35.00%**（窗口 `756` 交易日）
3. **ROE 改善**：相对上一披露期上升 ≥ **0.50%**（百分点/小数按数据口径）
4. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
5. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
6. **出场（任一触发）**：止损 **−12.00%**；持有满 **20** 个交易日

信号实现：`signal_roe_improve_pb_cheap`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一腿

来源：`data/factors/roe_improve_pb_cheap_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sh.603986** |
| 开仓 | 2017-08-28，约 28.19 元 |
| 清仓 | 2017-09-25，约 44.46 元 |
| 单腿涨跌 | **57.72%** |
| 当日组合贡献 | NAV 7.21% |
| 出场备注 | hold_end；买入2017-08-28 成本价28.1856 |

**开仓信号备注**：ROE改善+低PB

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only roe_improve_pb_cheap --limit 40
python scripts/run_new_factors.py --only roe_improve_pb_cheap --limit 0
```

产物：`data/factors/roe_improve_pb_cheap_*`
