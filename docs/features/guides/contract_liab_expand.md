# 合同负债扩张（contract_liab_expand）

合同负债/预收款同比或环比明显上升（需求领先指标，新准则后预收多计入合同负债）。

标签：`基本面` · `合同负债` · `预收款` · `领先指标`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **合同负债/预收款扩张**：同比 ≥ 15.00% 或 环比 ≥ 8.00%（新准则合同负债与旧准则预收款合并口径）
3. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
4. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
5. **出场（任一触发）**：止损 **−12.00%**；持有满 **30** 个交易日

信号实现：`signal_contract_liab_expand`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一腿

来源：`data/factors/contract_liab_expand_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sz.002602** |
| 开仓 | 2016-10-25，约 9.131 元 |
| 清仓 | 2016-12-06，约 14.11 元 |
| 单腿涨跌 | **54.54%** |
| 当日组合贡献 | NAV 6.82% |
| 出场备注 | hold_end；买入2016-10-25 成本价9.1309 |

**开仓信号备注**：合同负债/预收款扩张

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only contract_liab_expand --limit 40
python scripts/run_new_factors.py --only contract_liab_expand --limit 0
```

产物：`data/factors/contract_liab_expand_*`
