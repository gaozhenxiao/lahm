# 地量后反弹（turnover_dryup_bounce）

换手率先极度萎缩（地量），再放量并站上 MA20——典型的「冷却后重新定价」技术结构。

## 怎么选股（逐步）

1. **地量**：前一日换手 ≤ 20 日均换手的约 **55%**（`dry_ratio`）  
2. **放量**：当日换手 ≥ 20 日均换手的约 **1.2 倍**（`surge_ratio`）  
3. **图形·回踩确认**：收盘上穿 **MA20**  
4. **组合约束**：等权；到期 / 止损  

信号实现：`signal_turnover_dryup_bounce`。

## 适用与注意

- 无财务闸门；可与质量/估值因子叠用，但本文件描述的是独立技术版。  
- 地量也可能是无人问津的阴跌，放量确认不可或缺。  
- 若列表中已退役，仅作历史说明参考。

## 怎么跑

```bash
python scripts/run_new_factors.py --only turnover_dryup_bounce --limit 40
python scripts/run_new_factors.py --only turnover_dryup_bounce --limit 0
```

产物：`data/factors/turnover_dryup_bounce_*`
