# 成长不贵回踩（growth_not_expensive_pullback）

高增且PE分位不高，回踩站上MA20并处在MA60上方。

标签：`基本面` · `技术面` · `成长` · `估值`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **估值闸门**：PE 历史分位 ≤ **45.00%**（窗口 `756` 交易日）
3. **成长闸门**：净利/营收同比 ≥ **20.00%**
4. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
5. **回撤过滤**：近 20 日回撤 ≤ **−4.00%**（避免追高）
6. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
7. **出场（任一触发）**：止损 **−12.00%**；持有满 **25** 个交易日

信号实现：`signal_growth_not_expensive_pullback`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一腿

来源：`data/factors/growth_not_expensive_pullback_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sh.600233** |
| 开仓 | 2016-06-15，约 14.92 元 |
| 清仓 | 2016-07-20，约 19.76 元 |
| 单腿涨跌 | **32.42%** |
| 当日组合贡献 | NAV 4.05% |
| 出场备注 | hold_end；买入2016-06-15 成本价14.9219 |

**开仓信号备注**：成长不贵回踩

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only growth_not_expensive_pullback --limit 40
python scripts/run_new_factors.py --only growth_not_expensive_pullback --limit 0
```

产物：`data/factors/growth_not_expensive_pullback_*`
