# 二十日急跌反弹（ret20_extreme_bounce）

20日跌幅过深后，收盘重新站上MA20。

标签：`超卖` · `反弹` · `均线`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
3. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
4. **出场（任一触发）**：止损 **−10.00%**；持有满 **10** 个交易日

信号实现：`signal_ret20_extreme_bounce`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一笔

来源：`data/factors/ret20_extreme_bounce_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sz.300450 先导智能** |
| 开仓 | 2016-02-02，约 7.813 元 |
| 清仓 | 2016-02-23，约 11.15 元 |
| 单笔涨跌 | **42.74%** |
| 当日组合贡献 | NAV 5.34% |
| 出场备注 | hold_end；买入2016-02-02 成本价7.8130 |

**开仓信号备注**：20日急跌后站上MA20

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only ret20_extreme_bounce --limit 40
python scripts/run_new_factors.py --only ret20_extreme_bounce --limit 0
```

产物：`data/factors/ret20_extreme_bounce_*`
