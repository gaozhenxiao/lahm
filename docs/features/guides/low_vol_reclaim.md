# 低波动回踩（low_vol_reclaim）

**基本面/结构色彩偏弱、偏技术**：波动率处于自身历史低分位时，等待收盘重新站上 MA20，属于「安静盘整后的启动确认」。

## 怎么选股（逐步）

1. **波动闸门**：近 60 日波动率在自身约 252 日窗口内的分位 ≤ **30%**（默认 `vol_pct_max=0.30`）  
2. **图形·回踩确认**：收盘价上穿 **MA20**（昨日在下、今日站上）  
3. **组合约束**：等权持仓；到期或止损离场  

信号实现：`signal_low_vol_reclaim`。

## 适用与注意

- 更适合震荡后方向选择，**不是**财报驱动主线。  
- 低波动也可能是阴跌中继，需结合仓位上限与止损。  
- 若列表中已退役，仅作历史说明参考。

## 怎么跑

```bash
python scripts/run_new_factors.py --only low_vol_reclaim --limit 40
python scripts/run_new_factors.py --only low_vol_reclaim --limit 0
```

产物：`data/factors/low_vol_reclaim_*`
