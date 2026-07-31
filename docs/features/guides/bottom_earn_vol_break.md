# 底部业绩放量突破（bottom_earn_vol_break）

对齐 **仕佳光子 688313** 路径：长期磨底 → 业绩扭亏/同比转好 → 缩量蓄势后放量突破。

## 逻辑

1. **底部**：一年内触底，且仍深度回撤或处在底部区；相对一年低点涨幅 ≤55%（避免追高）  
2. **业绩**：历史上曾偏弱/亏损，当前同比转正或 ROE 转好，且近 180 日有转好事件  
3. **量价**：先缩量蓄势，再放量；允许放量后 5 日内完成 20/60 日突破  
4. **风控**：同股 20 日去抖；持有约 40 日，止损 15%  

## 怎么跑

```bash
python scripts/run_new_factors.py --only bottom_earn_vol_break --limit 40
python scripts/run_new_factors.py --only bottom_earn_vol_break --limit 0
```

产物：`data/factors/bottom_earn_vol_break_*`
