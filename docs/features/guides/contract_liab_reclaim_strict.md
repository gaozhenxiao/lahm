# 合同负债扩张回踩(严)（contract_liab_reclaim_strict）

更高同比/环比门槛的合同负债回踩。

标签：`基本面` · `技术面` · `合同负债`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **合同负债/预收款扩张**：同比 ≥ 20.00% 或 环比 ≥ 12.00%（新准则合同负债与旧准则预收款合并口径）
3. **财务热窗**：上述财务事件发生后的 **25** 个交易日内才允许技术信号
4. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
5. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
6. **出场（任一触发）**：止损 **−12.00%**；持有满 **25** 个交易日

信号实现：`signal_contract_liab_reclaim`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一腿

来源：`data/factors/contract_liab_reclaim_strict_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sh.601919** |
| 开仓 | 2021-03-26，约 5.181 元 |
| 清仓 | 2021-05-06，约 8.264 元 |
| 单腿涨跌 | **59.53%** |
| 当日组合贡献 | NAV 7.44% |
| 出场备注 | hold_end；买入2021-03-26 成本价5.1805 |

**开仓信号备注**：合同负债扩张回踩

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only contract_liab_reclaim_strict --limit 40
python scripts/run_new_factors.py --only contract_liab_reclaim_strict --limit 0
```

产物：`data/factors/contract_liab_reclaim_strict_*`
