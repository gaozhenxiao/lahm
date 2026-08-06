# 三模块 + 因子

## 模块

| 模块 | 路由 | API |
|------|------|-----|
| Leads 机会列表 | `/leads` | `/api/leads/` |
| Factors 因子列表 | `/factors` | `/api/factors/` |
| Investments 投资列表 | `/investments` | `/api/investments/` |

Leads 支持：新建 / 状态流转 / 从筛选批量导入（`POST /api/leads/from-screening`）/ 转入投资。

## 国家队因子 `national_team`

**完整技术文档** → [`national-team-factor.md`](./national-team-factor.md)

摘要：

1. **信号**：汇金高占比沪深300 ETF（510300/510310/510330）份额 `share_z`
2. **交易**：时代篮子（早期宽基 → 银行+科创）
3. **仓位**：
   - `continuous`：底仓 10%、随份额连续加减，可反复进出（默认主产物）
4. **自动运行**：jx 后端启动时异步刷新点信号；工作日 Cron 日更（见技术文档 §9）

回测：

```powershell
cd d:\cursor_space\jx
python scripts\backtest_national_team_factor.py --logic long_hold --mode long_flat
python scripts\backtest_national_team_factor.py --logic continuous --mode long_flat
python scripts\backtest_national_team_factor.py --logic compare --mode long_flat
```

## 暴跌抄底因子 `dip_buy`

**文档** → [`dip-buy-factor.md`](./dip-buy-factor.md)

摘要：多指数急跌/回撤 × PE/PB 历史分位闸门（高估不抄、低估加仓）。

```powershell
python scripts\refresh_dip_buy_data.py --backtest
python scripts\backtest_dip_buy_factor.py
```
