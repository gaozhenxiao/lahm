# PEG成长合理价（peg_garp）

高增长且PE分位相对增长偏低（PEG近似），站上MA20。

标签：`自研` · `PEG` · `GARP` · `林奇`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **成长闸门**：净利/营收同比 ≥ **20.00%**
3. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
4. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
5. **出场（任一触发）**：止损 **−12.00%**；持有满 **20** 个交易日

信号实现：`signal_peg_garp`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一笔

来源：`data/factors/peg_garp_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sz.002600** |
| 开仓 | 2019-08-14，约 5.772 元 |
| 清仓 | 2019-09-11，约 9.132 元 |
| 单笔涨跌 | **58.23%** |
| 当日组合贡献 | NAV 7.28% |
| 出场备注 | hold_end；买入2019-08-14 成本价5.7717 |

**开仓信号备注**：PEG-GARP(YOYNI)

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only peg_garp --limit 40
python scripts/run_new_factors.py --only peg_garp --limit 0
```

产物：`data/factors/peg_garp_*`
