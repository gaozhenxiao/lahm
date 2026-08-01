# 新因子批次说明

统一框架：本地/baostock 日线 + 季度财务 + **「基本面闸门 + 技术图形确认」** + 等权收盘调仓回测。

每个因子说明（页面或 `docs/features/guides/<id>.md`）现包含：

1. **怎么选股（逐步）**：财务条件、热窗、横盘突破/趋势回踩等图形、出场  
2. **举例**：回测 `*_trade_history.csv` 中的真实一腿（若有）  
3. **回测摘要 / 怎么跑**

批量重生成：`python scripts/generate_factor_guides.py`  
（UI 用同一套步骤生成器自动补强过简说明。）

## 通宵挖掘冠军（2026-08-01）

| id | Sharpe | 备注 |
|---|---|---|
| **gross_expand_champ_tp35** | **1.816** | 毛利率扩张突破 + 净利≥0.10 + 止盈35%；详见 [gross_expand_champ_tp35.md](gross_expand_champ_tp35.md) |
| gross_expand_brk60_m17_np10_lag29 | 1.802 | 原冠（无止盈）入场高原；**已冻结，勿再调参** |

## 新结构主线（财务 × 图形）

| id | 结构 | 说明 |
|---|---|---|
| demand_pricing_break | 合同负债扩张 × 毛利率扩张 × 突破 | [demand_pricing_break.md](demand_pricing_break.md) |
| demand_pricing_base | 同上 × 横盘箱体突破 | [demand_pricing_base.md](demand_pricing_base.md) |
| demand_pricing_pullback | 同上 × 趋势回踩 | [demand_pricing_pullback.md](demand_pricing_pullback.md) |
| cl_intensity_* | 预收强度（合同负债/营收）× 图形 | [cl_intensity_break.md](cl_intensity_break.md) |
| contract_liab_reclaim | 合同负债扩张 × MA20 回踩 | [contract_liab_reclaim.md](contract_liab_reclaim.md) |
| rev_qoq_* | 营收环比 × 突破/横盘 | [rev_qoq_break.md](rev_qoq_break.md) |
| gp_consec_* | 毛利率连续两期扩张 × 图形 | [gp_consec_break.md](gp_consec_break.md) |

纪要：[`../overnight_factor_mining.md`](../overnight_factor_mining.md) · 快照：`data/factors/overnight_champion.json`  
毛利率高原停止参数微调；通宵见 `overnight_pause.json`。

## 怎么批量跑

```bash
python scripts/run_new_factors.py --limit 40
python scripts/run_new_factors.py --limit 0
python scripts/chain_factor_backtests.py
python scripts/generate_factor_guides.py
```

行情/财务缓存：`data/factors/_shared/`。

## 当前保留因子

回测成本默认：佣金万分之一（双向）+ 卖出印花税千分之一。各 id 的详细选股步骤见同名 `.md`。

| id | 名称 | 备注 |
|---|---|---|
| pb_low_ma_reclaim | 低PB回踩确认 | 估值 × 回踩 |
| double_cheap_reclaim | 双低估回踩 | PE+PB × 回踩 |
| growth_breakout | 高增突破 | 成长 × 突破 |
| oversold_roe_bounce | 急跌ROE反弹 | 质量 × 超卖回踩 |
| pead_roe_drift | ROE改善漂移 | 财报后 × 回踩 |
| pb_below_one_reclaim | 破净回踩 | 估值 × 回踩 |
| pe_quality_cross | 低估值质量金叉 | 估值+质量 × 均线 |
| cheap_roe_bounce | 低估高ROE急跌反弹 | 估值+质量 × 反弹 |
| high_margin_pullback | 高净利率动量回踩 | 利润率 × 回踩 |
| eps_growth_reclaim | 盈利增长站上均线 | 成长 × 均线 |
| ma_trend_quality | 质量趋势金叉 | 质量 × 趋势 |
| pe_low_ma_reclaim | 低PE回踩确认 | 估值 × 回踩 |
| volume_breakout | 放量突破 | 技术 |
| narrow_range_breakout | 窄幅突破 | 技术 |
| turn_surge_ma_reclaim | 换手放大上均线 | 技术 |
| boll_lower_reclaim | 布林下轨反弹 | 技术 |
| new_high_pullback | 新高回踩 | 技术 |
| dual_ma_volume | 放量金叉 | 技术 |
| ret20_extreme_bounce | 二十日急跌反弹 | 技术 |
| amount_shrink_breakout | 缩量后放量突破 | 技术 |

优先跑基本面批次：

```bash
python scripts/run_new_factors.py --limit 40 --only pb_low_ma_reclaim,double_cheap_reclaim,growth_breakout,oversold_roe_bounce,pead_roe_drift,pb_below_one_reclaim,pe_quality_cross,cheap_roe_bounce,high_margin_pullback,eps_growth_reclaim,ma_trend_quality,pe_low_ma_reclaim
```

另有稳定因子：`national_team` / `dip_buy` / `earnings_forecast` / `dividend_etf_swing`（各自有专文说明）。

冒烟负收益因子已下线（不再出现在因子列表）。
