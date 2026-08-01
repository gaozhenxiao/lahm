# 通宵因子挖掘纪要（2026-07-31 → 2026-08-01）

流水线：`scripts/mine_overnight.py`（冒烟 limit40 → 全量 limit0 → 图表 → Mongo sync）。  
评判优先 **Sharpe**（非 total_return）。主线约束：**基本面 × 技术**，放弃纯量价。

## 冻结声明（重要）

**毛利率扩张入场高原已冻结，不再做参数微调。**

包括但不限于：

- `gross_expand_brk60_m17_np10_lag29` 及其 lag / hold / stop / imp / m16–m19 / brk55–65 / np09–11 网格  
- 在同一入场上叠加 ROE/PE/PB、动量帽、缩量、近突破、软增长等过滤  
- 止盈/移动止损的细网格（tp32–38 等）——**tp35 已定为冠军出场，停止拧螺丝**

原因：该结构附近已形成明显高原（Sharpe ≈ 1.80–1.82），继续挖属于样本内调参，过拟合风险高、边际信息低。  
后续若重启挖掘，应换**真正不同的因子结构**（新信号逻辑），而不是同一公式换阈值。

暂停开关：存在 `data/factors/overnight_pause.json` 时，通宵挖掘循环跳过跑波。

## 冠军

**`gross_expand_champ_tp35`** — Sharpe **1.8163**，总收益 **50.94%**（321 腿）

| 参数 | 值 | 含义 |
|---|---|---|
| margin_improve | 0.006 | 毛利率环比至少升 0.6pct |
| margin_min | 0.17 | 毛利率水平 ≥ 17% |
| np_min | 0.10 | 净利率 ≥ 10% |
| funda_lag | 29 | 财报事件后 29 日内可交易 |
| break_days | 60 | 突破 60 日高 |
| hold_days | 51 | 最长持有 |
| stop_loss | 0.12 | 止损 12% |
| take_profit | **0.35** | 止盈 35%（相对原冠的关键增量） |

### 选股一句话

沪深300里，**毛利率刚明显扩张且净利率不差**的公司，在财报后约一个月内若**放量突破近两月新高并站上均线**，等权买入；涨 35% 止盈，跌 12% 止损，否则最多拿约 51 个交易日。

详细步骤与真实案例（沪电股份 2019-08-30 入场、+35% 止盈离场）见：  
[`guides/gross_expand_champ_tp35.md`](guides/gross_expand_champ_tp35.md)

机器可读快照：[`data/factors/overnight_champion.json`](../../data/factors/overnight_champion.json)

## 高原排行（去重 Top，仅作归档）

| Sharpe | id | 备注 |
|---|---|---|
| 1.8163 | gross_expand_champ_tp35 | **冠军**（wave80） |
| 1.8163 | gross_expand_ma60_tp35 | 并列（过滤未改信号） |
| 1.8017 | gross_expand_brk60_m17_np10_lag29 | 原冠，无止盈 |
| 1.8008 | gross_expand_brk60_m18_np10_lag29 | 近冠 |
| 1.7964 | gross_high_np_m17_lag30_np10 | high_np 高原 |
| 1.7660 | gross_expand_champ_tp30 | 止盈偏紧 |

## 关键结论

1. **入场高原已挖穿**，冻结微调。  
2. **止盈是有效抬升**：同一入场 + tp35 → Sharpe 1.80→1.816；更紧/更宽止盈与 trail 均不如 35%。  
3. **多数附加过滤拖累**：质量/估值、软增长、动量帽、缩量、近突破、连续毛利、双同比等。  
4. **次峰** `gp_np_*` ≈ 1.51，结构不同但未超冠；若再挖可从「新结构」角度评估，而不是并入冠军网格。  
5. 出场扩展：`runner.build_legs_from_entries` 已支持 `take_profit` / `trail_stop`。

## 运维

```bash
# 通宵循环（若存在 overnight_pause.json 则跳过跑波）
python -u scripts/mine_overnight.py --sleep-sec 180

# 仅同步登记到 Mongo（不淘汰）
python scripts/sync_prune_and_mongo.py --sync-only
```

状态：`data/factors/overnight_state.json`  
累计保留：`data/factors/overnight_keep.json`  
日志：`data/factors/mine_overnight.log`
