# 物理世界结构因子挖掘 · Round1

原则：
1. **核心诉求 = 对未来的预测能力**（时间外推 / 近端时段表现），不是「从已有标的向别的标的拓展」。
2. **换结构故事，不拧出场**（hold40 / sl12 / tp30 / lag28 / brk60）。
3. 指数池 / 行业池只是**样本设计**（降噪、对准物理机制发生的地方），**不是**以跨池可迁移当录取门槛。
4. 排序主键：`tw_score`（近端权重大）+ `recent2y_sharpe`；全样本 Sharpe 只作辅证。

## 物理字段（本地 `1.0_A股财务数据库.db`）

| 字段 | 含义 |
|------|------|
| `fin_cash_collect` | 销售商品收现 / 营收 |
| `fin_cip` / `fin_cip_delta` / `fin_fa_delta` | 在建工程与固定资产变化（转固） |
| `fin_ap_to_rev` | 应付账款 / 营收 |
| `fin_capex_to_rev` | 购建固资等现金流出 / 营收 |
| `fin_cfo_yoy` / `fin_cfo_yoy_accel` | 经营现金流同比及二阶 |

## 信号族

| family | signal | 故事 |
|--------|--------|------|
| cash_collect | `signal_cash_collect_up_break` | 客户真金白银付款改善 |
| cip_convert | `signal_cip_convert_break` | 产能落地（CIP↓+FA↑） |
| ap_credit | `signal_ap_credit_rev_break` | 扩张占用供应商信用 |
| capex_cycle | `signal_capex_cycle_break` | 资本开支强度上行 |
| cfo_yoy_accel | `signal_cfo_yoy_accel_break` | 现金利润 YoY 再加速 |

## 已登记（HS300）

`phys_cash_collect_hs300` · `phys_cip_convert_hs300` · `phys_ap_credit_hs300` · `phys_capex_cycle_hs300` · `phys_cfo_accel_hs300`

## 已登记（CSI500）

`phys_capex_cycle_csi500` — 挖掘冠军 `phys_capex__cx02_ry05`（tw≈0.72，近两年 Sharpe≈0.98）

## CSI1000 快照（2026-08-05）

冠军：**应付授信** `ap02_ry08_np03` — tw≈0.54，**近两年 Sharpe≈1.49**（全样本 0.28 仅辅证）。  
按「预测力」口径值得重视；不因「CSI500 是 capex」而否决。暂未入库。

## 行业首批（C39/C38/C35/C36）— 按近端预测力看

| 候选 | tw | r2y_sh | full_sh | 说明 |
|------|----|--------|---------|------|
| C38 CFO `cfoacc10` | 0.51 | **1.13** | 0.15 | 近端预测强 |
| C35 AP `ap015` | 0.40 | **1.28** | 0.19 | 近端强 |
| C36 转固 `cip_basic` | 0.53 | 0.76 | 0.42 | tw 高且全样本不塌 |
| C35 转固 `cip_basic` | 0.43 | 0.69 | **0.53** | 全样本最稳 |

行业池用途：让转固/CFO 等机制在更干净样本里估预测力，**不是**考「能否从沪深300推广到汽车」。详见 `mine_phys_industry_round1/ROUND_SUMMARY.md`。

## 已登记（行业 · Sharpe≥0.30）

| UI | factor_id | Sharpe | 池 |
|----|-----------|--------|-----|
| #241 | `phys_cip_convert_c36` | 0.42 | C36 汽车 |
| #243 | `phys_capex_cycle_c38` | 0.30 | C38 电气 |

已删（pad 保序）：#239 `phys_cip_convert_c35` · #240 `phys_cip_convert_c35_ry05` · #242 `phys_cash_collect_c38`。

### HS300 快照（2026-08-05）

| 因子 | Sharpe | 近2年要点 |
|------|--------|-----------|
| `phys_cfo_accel_hs300` | **1.03** | 全样本最强；近两年偏弱 |
| `phys_cip_convert_hs300` | 0.51 | 近两年 Sharpe≈1.05（tw 冠军结构） |
| `phys_ap_credit_hs300` | 0.59 | 时段较稳 |
| `phys_cash_collect_hs300` | 0.55 | 腿最多 |
| `phys_capex_cycle_hs300` | 0.41 | 近两年尚可 |

详见：`data/factors/mine_phys_struct_round1/ROUND_SUMMARY.md`

## 范围 / 行业挖掘

在不同样本池估同一结构的**时间外推**；跨池结果不同只说明机制/噪声环境不同，**不**用「可迁移」当否决票。

```bash
# 中证1000
.venv\Scripts\python.exe scripts/mine_phys_struct_round1.py --universes csi1000 --skip-build

# 行业范围（电子/电气/设备/汽车/化工/医药/有色/软件…）
.venv\Scripts\python.exe scripts/mine_phys_industry_round1.py
.venv\Scripts\python.exe scripts/mine_phys_industry_round1.py --industries C39,C38,C36 --min-n 80
```

产物：`data/factors/mine_phys_industry_round1/`；宇宙缓存 `universe_ind_<slug>.parquet`。

## 跑法

```bash
.venv\Scripts\python.exe scripts/mine_phys_struct_round1.py --universes hs300,csi500,csi1000 --skip-build
.venv\Scripts\python.exe scripts/run_new_factors.py --limit 0 --only phys_capex_cycle_csi500
.venv\Scripts\python.exe scripts/run_new_factors.py --limit 0 --only phys_cip_convert_hs300,phys_ap_credit_hs300
```

产物目录：`data/factors/mine_phys_struct_round1/`
