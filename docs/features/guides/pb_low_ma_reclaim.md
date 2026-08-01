# 低PB回踩确认（pb_low_ma_reclaim）

PB历史分位偏低时，等待收盘重新站上MA60，避免单纯抄底。

标签：`估值` · `PB` · `均线` · `回踩`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **估值闸门**：PB 历史分位 ≤ **25.00%**（窗口 `756` 交易日）
3. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
4. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
5. **出场（任一触发）**：止损 **−12.00%**；持有满 **20** 个交易日

信号实现：`signal_pb_low_ma_reclaim`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一腿

来源：`data/factors/pb_low_ma_reclaim_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sh.600893** |
| 开仓 | 2020-07-01，约 23.36 元 |
| 清仓 | 2020-07-29，约 37.36 元 |
| 单腿涨跌 | **59.92%** |
| 当日组合贡献 | NAV 7.49% |
| 出场备注 | hold_end；买入2020-07-01 成本价23.3597 |

**开仓信号备注**：低PB分位回踩确认站上MA60

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only pb_low_ma_reclaim --limit 40
python scripts/run_new_factors.py --only pb_low_ma_reclaim --limit 0
```

产物：`data/factors/pb_low_ma_reclaim_*`
