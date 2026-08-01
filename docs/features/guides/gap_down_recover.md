# 跳空低开修复（gap_down_recover）

捕捉「恐慌性低开」后的日内/短线修复：低开留下缺口后，收盘重新站回关键均线或开盘参考位。

## 怎么选股（逐步）

1. **跳空**：当日开盘相对昨收明显低开（缺口）  
2. **修复确认**：收盘收回均线（如 MA20）或填补部分缺口  
3. **组合约束**：等权；短持有期 + 止损  

信号实现：`signal_gap_down_recover`（见 `signal_specs.py`）。

## 适用与注意

- 偏事件/情绪修复，**不是**财报基本面主线。  
- 假修复（跌停打开再砸）常见，务必严格止损。  
- 若列表中已退役，仅作历史说明参考。

## 怎么跑

```bash
python scripts/run_new_factors.py --only gap_down_recover --limit 40
python scripts/run_new_factors.py --only gap_down_recover --limit 0
```

产物：`data/factors/gap_down_recover_*`
