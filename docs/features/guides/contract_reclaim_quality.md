# 合同负债扩张质量回踩（contract_reclaim_quality）

合同负债扩张且ROE达标，回踩站上MA20。

标签：`基本面` · `技术面` · `合同负债` · `质量`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **质量底线**：ROE ≥ **8.00%**
3. **合同负债/预收款扩张**：同比 ≥ 12.00% 或 环比 ≥ 8.00%（新准则合同负债与旧准则预收款合并口径）
4. **财务热窗**：上述财务事件发生后的 **30** 个交易日内才允许技术信号
5. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
6. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
7. **出场（任一触发）**：止损 **−12.00%**；持有满 **25** 个交易日

信号实现：`signal_contract_reclaim_quality`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一腿

来源：`data/factors/contract_reclaim_quality_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sh.600196** |
| 开仓 | 2021-04-01，约 37.3 元 |
| 清仓 | 2021-05-12，约 58.73 元 |
| 单腿涨跌 | **57.43%** |
| 当日组合贡献 | NAV 7.18% |
| 出场备注 | hold_end；买入2021-04-01 成本价37.3036 |

**开仓信号备注**：合同负债扩张质量回踩

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only contract_reclaim_quality --limit 40
python scripts/run_new_factors.py --only contract_reclaim_quality --limit 0
```

产物：`data/factors/contract_reclaim_quality_*`
