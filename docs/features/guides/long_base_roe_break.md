# 长横盘ROE突破（long_base_roe_break）

120日振幅收窄后ROE改善，突破箱体上沿。

标签：`基本面` · `技术面` · `横盘` · `ROE`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **ROE 改善**：相对上一披露期上升 ≥ **0.40%**（百分点/小数按数据口径）
3. **财务热窗**：上述财务事件发生后的 **25** 个交易日内才允许技术信号
4. **图形·收窄后突破**：振幅 ≤ 28.00% 的横盘背景下，收盘 ≥ 昨日起算 **60** 日高，且 > MA20
5. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
6. **出场（任一触发）**：止损 **−12.00%**；持有满 **30** 个交易日

信号实现：`signal_long_base_roe_break`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一腿

来源：`data/factors/long_base_roe_break_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sh.600030** |
| 开仓 | 2024-09-25，约 20.26 元 |
| 清仓 | 2024-11-13，约 31.53 元 |
| 单腿涨跌 | **55.58%** |
| 当日组合贡献 | NAV 6.95% |
| 出场备注 | hold_end；买入2024-09-25 成本价20.2648 |

**开仓信号备注**：长横盘ROE改善突破

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only long_base_roe_break --limit 40
python scripts/run_new_factors.py --only long_base_roe_break --limit 0
```

产物：`data/factors/long_base_roe_break_*`
