# 合同负债高同比回踩（contract_yoy_reclaim）

合同负债同比高增后回踩站上MA20。

标签：`基本面` · `技术面` · `合同负债`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **合同负债/预收款扩张**：同比 ≥ 20.00%（新准则合同负债与旧准则预收款合并口径）
3. **财务热窗**：上述财务事件发生后的 **30** 个交易日内才允许技术信号
4. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
5. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
6. **出场（任一触发）**：止损 **−12.00%**；持有满 **25** 个交易日

信号实现：`signal_contract_yoy_reclaim`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一笔

来源：`data/factors/contract_yoy_reclaim_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sz.002558 巨人网络** |
| 开仓 | 2025-05-26，约 14.35 元 |
| 清仓 | 2025-07-01，约 22.81 元 |
| 单笔涨跌 | **58.97%** |
| 当日组合贡献 | NAV 7.37% |
| 出场备注 | hold_end；买入2025-05-26 成本价14.3461 |

**开仓信号备注**：合同负债高同比回踩

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only contract_yoy_reclaim --limit 40
python scripts/run_new_factors.py --only contract_yoy_reclaim --limit 0
```

产物：`data/factors/contract_yoy_reclaim_*`
