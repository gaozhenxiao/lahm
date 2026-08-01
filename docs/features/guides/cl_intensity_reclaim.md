# 合同负债强度回踩（cl_intensity_reclaim）

预收强度上升热窗口内站上MA20。

标签：`基本面` · `技术面` · `合同负债` · `新结构`

## 怎么选股（逐步）

1. **股票池**：默认 `hs300` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。
2. **预收强度**：合同负债 / 营收 ≥ **5.00%**，且强度环比升幅 ≥ **8.00%**（过滤非预收型噪声）
3. **财务热窗**：上述财务事件发生后的 **30** 个交易日内才允许技术信号
4. **图形·回踩确认**：收盘价上穿 **MA20**（昨日在下、今日站上）
5. **组合约束**：最多同时持有 **8** 只，等权；有空位才开新仓
6. **出场（任一触发）**：止损 **−12.00%**；持有满 **35** 个交易日

信号实现：`signal_cl_intensity_break`（`app/services/factors/signal_specs.py`）。

## 怎么跑

```bash
python scripts/run_new_factors.py --only cl_intensity_reclaim --limit 40
python scripts/run_new_factors.py --only cl_intensity_reclaim --limit 0
```

产物：`data/factors/cl_intensity_reclaim_*`
