# 新因子批次说明

统一框架：`baostock` 日线/季度财务 +「基本面闸门 + K 线确认」+ 等权收盘调仓回测。

## 怎么批量跑

```bash
# 冒烟（前 N 只）
python scripts/run_new_factors.py --limit 40

# 全量沪深300（慢，建议挂机）
python scripts/run_new_factors.py --limit 0

# 只跑指定
python scripts/run_new_factors.py --only growth_breakout,volume_breakout --limit 0
```

行情/财务缓存目录：`data/factors/_shared/`（跨因子复用）。

## 因子清单（注册表）

| id | 名称 | 类型 |
|---|---|---|
| pb_low_ma_reclaim | 低PB回踩确认 | 基本面 |
| pe_low_ma_reclaim | 低PE回踩确认 | 基本面 |
| double_cheap_reclaim | 双低估回踩 | 基本面 |
| cheap_roe_bounce | 低估ROE反弹 | 基本面 |
| growth_breakout | 高增突破 | 基本面 |
| eps_growth_reclaim | 增长站上均线 | 基本面 |
| ma_trend_quality | 质量均线金叉 | 基本面 |
| high_margin_pullback | 高利润率回踩 | 基本面 |
| oversold_roe_bounce | 急跌ROE反弹 | 基本面 |
| pead_roe_drift | ROE改善漂移 | 基本面 |
| pb_below_one_reclaim | 破净回踩 | 基本面 |
| low_vol_reclaim | 低波动回踩 | 技术 |
| momentum_ma_pullback | 动量回踩 | 技术 |
| volume_breakout | 放量突破 | 技术 |
| ma120_pullback | 长线多头回踩 | 技术 |
| turnover_dryup_bounce | 地量反弹 | 技术 |
| narrow_range_breakout | 窄幅突破 | 技术 |
| gap_down_recover | 跳空修复 | 技术 |
| consecutive_down_bounce | 连跌反弹 | 技术 |
| turn_surge_ma_reclaim | 换手放大上均线 | 技术 |
| boll_lower_reclaim | 布林下轨反弹 | 技术 |
| new_high_pullback | 新高回踩 | 技术 |
| dual_ma_volume | 放量金叉 | 技术 |
| pe_quality_cross | 低估值质量金叉 | 基本面 |
| ret20_extreme_bounce | 二十日急跌反弹 | 技术 |
| amount_shrink_breakout | 缩量后放量突破 | 技术 |

另有既有稳定因子：`national_team` / `dip_buy` / `earnings_forecast`。

全量挂机：

```bash
python scripts/chain_factor_backtests.py
```

## 冒烟结果说明

`--limit 25` 仅为通路验证，收益不代表全样本；以 `--limit 0` 全量回测为准。
