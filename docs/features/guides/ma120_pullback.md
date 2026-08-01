# 长线回踩（ma120_pullback）

**趋势结构 + 短线确认**：价格与 MA20 均在 MA120 上方（长线多头），回撤后收盘重新站上 MA20。

## 怎么选股（逐步）

1. **长线多头**：收盘 > **MA120**，且 MA20 > MA120  
2. **回撤过滤**：近 20 日回撤 ≤ **−2%**（默认 `dd_need`，避免刚突破就追）  
3. **图形·回踩确认**：收盘上穿 **MA20**  
4. **组合约束**：等权；持有期满或止损离场  

信号实现：`signal_ma120_pullback`。

## 适用与注意

- 抓的是「大趋势未坏、短线洗盘结束」的再介入。  
- 无财务闸门，熊市假多头阶段假信号更多。  
- 若列表中已退役，仅作历史说明参考。

## 怎么跑

```bash
python scripts/run_new_factors.py --only ma120_pullback --limit 40
python scripts/run_new_factors.py --only ma120_pullback --limit 0
```

产物：`data/factors/ma120_pullback_*`
