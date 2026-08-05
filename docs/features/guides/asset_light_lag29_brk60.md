# 轻资产高增突破(滞后29)（asset_light_lag29_brk60）

净利高增且资产克制后突破。

标签：`基本面` · `技术面` · `增长`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **成长闸门**：净利/营收同比 ≥ **12.00%**
3. **财务热窗**：上述财务事件发生后的 **29** 个交易日内才允许技术信号
4. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
5. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
6. **出场（任一触发）**：止损 **−12.00%**；持有满 **51** 个交易日

信号实现：`signal_asset_light_efficiency`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一笔

来源：`data/factors/asset_light_lag29_brk60_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sz.300014** |
| 开仓 | 2019-12-04，约 24.59 元 |
| 清仓 | 2020-02-24，约 39.26 元 |
| 单笔涨跌 | **59.65%** |
| 当日组合贡献 | NAV 7.46% |
| 出场备注 | hold_end；买入2019-12-04 成本价24.5926 |

**开仓信号备注**：资产克制下的净利高增

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only asset_light_lag29_brk60 --limit 40
python scripts/run_new_factors.py --only asset_light_lag29_brk60 --limit 0
```

产物：`data/factors/asset_light_lag29_brk60_*`
