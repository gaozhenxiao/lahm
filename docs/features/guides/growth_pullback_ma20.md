# 高增回踩（growth_pullback_ma20）

高增长且近端回撤后站上MA20。

标签：`自研` · `成长` · `回踩`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **估值闸门**：PE 历史分位 ≤ **60.00%**（窗口 `756` 交易日）
3. **成长闸门**：净利/营收同比 ≥ **20.00%**
4. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
5. **回撤过滤**：近 20 日回撤 ≤ **−4.00%**（避免追高）
6. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
7. **出场（任一触发）**：止损 **−12.00%**；持有满 **20** 个交易日

信号实现：`signal_growth_pullback_ma20`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一腿

来源：`data/factors/growth_pullback_ma20_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sh.601058** |
| 开仓 | 2020-12-30，约 4.923 元 |
| 清仓 | 2021-01-28，约 7.775 元 |
| 单腿涨跌 | **57.92%** |
| 当日组合贡献 | NAV 7.24% |
| 出场备注 | hold_end；买入2020-12-30 成本价4.9234 |

**开仓信号备注**：高增回踩MA20

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only growth_pullback_ma20 --limit 40
python scripts/run_new_factors.py --only growth_pullback_ma20 --limit 0
```

产物：`data/factors/growth_pullback_ma20_*`
