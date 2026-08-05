# 归属净利领先突破（parent_lead_break）

YOYPNI 明显高于 YOYNI 后突破，抓并表质量改善。

标签：`基本面` · `技术面` · `归属净利` · `新结构`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **成长闸门**：净利/营收同比 ≥ **10.00%**
3. **归属领先**：YOYPNI − YOYNI ≥ **3.00%**
4. **归属质量**：母公司净利同比领先整体净利同比
5. **财务热窗**：上述财务事件发生后的 **28** 个交易日内才允许技术信号
6. **图形·突破确认**：收盘 ≥ 昨日起算 **60** 日最高价，且收盘 > **MA20**
7. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
8. **出场（任一触发）**：止损 **−12.00%**；持有满 **35** 个交易日

信号实现：`signal_parent_lead_break`（`app/services/factors/signal_specs.py`）。

## 举例：回测里真实成交的一笔

来源：`data/factors/parent_lead_break_trade_history.csv`

| 项目 | 内容 |
|---|---|
| 标的 | **sz.300274 阳光电源** |
| 开仓 | 2020-10-30，约 26.65 元 |
| 清仓 | 2020-12-18，约 42.12 元 |
| 单笔涨跌 | **58.07%** |
| 当日组合贡献 | NAV 7.26% |
| 出场备注 | hold_end；买入2020-10-30 成本价26.6476 |

**开仓信号备注**：归属净利领先突破

解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。案例用于理解规则，不构成推荐。

## 怎么跑

```bash
python scripts/run_new_factors.py --only parent_lead_break --limit 40
python scripts/run_new_factors.py --only parent_lead_break --limit 0
```

产物：`data/factors/parent_lead_break_*`
