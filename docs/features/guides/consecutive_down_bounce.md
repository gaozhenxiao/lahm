# 连跌后反弹（consecutive_down_bounce）

连续若干日收跌后，出现阳线且收盘站上 MA20——短线超卖后的技术性反弹结构。

## 怎么选股（逐步）

1. **连跌**：此前连续 ≥ **3** 日收盘价下跌（默认 `down_days=3`）  
2. **反转日**：当日收阳（收盘 > 开盘）  
3. **图形确认**：收盘站上 **MA20**  
4. **组合约束**：等权；短持有 + 止损  

信号实现：`signal_consecutive_down_bounce`。

## 适用与注意

- 纯价格形态，无财务过滤；适合做卫星仓，不宜作为通宵挖掘主线。  
- 单边熊市中「连跌后反弹」失败率高。  
- 若列表中已退役，仅作历史说明参考。

## 怎么跑

```bash
python scripts/run_new_factors.py --only consecutive_down_bounce --limit 40
python scripts/run_new_factors.py --only consecutive_down_bounce --limit 0
```

产物：`data/factors/consecutive_down_bounce_*`
