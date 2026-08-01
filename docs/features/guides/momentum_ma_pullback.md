# 动量回踩（momentum_ma_pullback）

中期动量为正时，回踩站上均线再跟进——典型的「趋势中继」技术结构。

## 怎么选股（逐步）

1. **动量闸门**：中期涨幅（如 60 日）高于设定下限  
2. **回撤**：近 20 日有一定回撤，避免追在加速浪顶端  
3. **图形·回踩确认**：收盘重新站上 **MA20**（或规则指定均线）  
4. **组合约束**：等权；到期 / 止损离场  

## 适用与注意

- 与「高净利率动量回踩」不同：本因子**不一定**带利润率闸门。  
- 动量因子在趋势市有效、反转市易受损；注意仓位与回撤。  
- 若列表中已退役，仅作历史说明参考。

## 怎么跑

```bash
python scripts/run_new_factors.py --only momentum_ma_pullback --limit 40
python scripts/run_new_factors.py --only momentum_ma_pullback --limit 0
```

产物：`data/factors/momentum_ma_pullback_*`
