# 德里曼低PE逆向（dreman_low_pe）

PE分位底部且盈利为正，站上MA60。

标签：`德里曼` · `逆向` · `PE`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **估值闸门**：PE 历史分位 ≤ **20.00%**（窗口 `756` 交易日）
3. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
4. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
5. **出场（任一触发）**：止损 **−12.00%**；持有满 **25** 个交易日

信号实现：`signal_dreman_low_pe`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一笔

来源：`data/factors/dreman_low_pe_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sz.301165** |
| 开仓 | 2024-09-10，约 16.37 元 |
| 清仓 | 2024-10-24，约 26.1 元 |
| 单笔涨跌 | **59.39%** |
| 当日组合贡献 | NAV 7.42% |
| 出场备注 | hold_end；买入2024-09-10 成本价16.3740 |

**开仓信号备注**：德里曼低PE逆向

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only dreman_low_pe --limit 40
python scripts/run_new_factors.py --only dreman_low_pe --limit 0
```

产物：`data/factors/dreman_low_pe_*`
