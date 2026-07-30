# 新因子批次说明

统一框架：`baostock` 日线/季度财务 +「基本面闸门 + K 线确认」+ 等权收盘调仓回测。

## 怎么批量跑

```bash
python scripts/run_new_factors.py --limit 40
python scripts/run_new_factors.py --limit 0
python scripts/chain_factor_backtests.py
```

行情/财务缓存：`data/factors/_shared/`。

## 当前保留因子

| id | 名称 | 备注 |
|---|---|---|
| pb_low_ma_reclaim | 低PB回踩确认 | 冒烟正收益 |
| double_cheap_reclaim | 双低估回踩 | 冒烟正收益 |
| growth_breakout | 高增突破 | 冒烟正收益 |
| oversold_roe_bounce | 急跌ROE反弹 | 冒烟正收益 |
| pead_roe_drift | ROE改善漂移 | 冒烟正收益 |
| volume_breakout | 放量突破 | 冒烟正收益 |
| narrow_range_breakout | 窄幅突破 | 冒烟正收益 |
| pb_below_one_reclaim | 破净回踩 | 冒烟正收益 |
| turn_surge_ma_reclaim | 换手放大上均线 | 冒烟正收益 |
| boll_lower_reclaim | 布林下轨反弹 | 待全量 |
| new_high_pullback | 新高回踩 | 待全量 |
| dual_ma_volume | 放量金叉 | 待全量 |
| pe_quality_cross | 低估值质量金叉 | 待全量 |
| ret20_extreme_bounce | 二十日急跌反弹 | 待全量 |
| amount_shrink_breakout | 缩量后放量突破 | 待全量 |

另有稳定因子：`national_team` / `dip_buy` / `earnings_forecast`。

冒烟负收益因子已下线（不再出现在因子列表）。
