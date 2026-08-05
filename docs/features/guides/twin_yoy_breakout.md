# 双同比高增突破（twin_yoy_breakout）

净利润与EPS同比同时高增，突破60日高。

标签：`自研` · `成长` · `突破`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **成长闸门**：净利/营收同比 ≥ **15.00%**
3. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
4. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
5. **出场（任一触发）**：止损 **−12.00%**；持有满 **20** 个交易日

信号实现：`signal_twin_yoy_breakout`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一笔

来源：`data/factors/twin_yoy_breakout_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sz.300251** |
| 开仓 | 2025-02-10，约 16.37 元 |
| 清仓 | 2025-03-06，约 23.59 元 |
| 单笔涨跌 | **44.06%** |
| 当日组合贡献 | NAV 9.84% |
| 出场备注 | hold_end；买入2025-02-10 成本价16.3720 |

**开仓信号备注**：双同比高增突破

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only twin_yoy_breakout --limit 40
python scripts/run_new_factors.py --only twin_yoy_breakout --limit 0
```

产物：`data/factors/twin_yoy_breakout_*`
