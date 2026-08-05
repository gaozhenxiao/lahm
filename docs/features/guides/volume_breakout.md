# 放量突破（volume_breakout）

成交额明显放大且收盘突破60日高点。

标签：`放量` · `突破`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
3. **动量不过热**：近 20 日涨幅 ≤ **25.00%**
4. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
5. **出场（任一触发）**：止损 **−12.00%**；持有满 **15** 个交易日

信号实现：`signal_volume_breakout`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一笔

来源：`data/factors/volume_breakout_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sh.600118** |
| 开仓 | 2020-01-08，约 22.72 元 |
| 清仓 | 2020-02-06，约 36.21 元 |
| 单笔涨跌 | **59.35%** |
| 当日组合贡献 | NAV 7.42% |
| 出场备注 | hold_end；买入2020-01-08 成本价22.7211 |

**开仓信号备注**：放量突破60日高

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only volume_breakout --limit 40
python scripts/run_new_factors.py --only volume_breakout --limit 0
```

产物：`data/factors/volume_breakout_*`
