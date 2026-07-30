# 柳暗花明（lahm）

面向 A 股研究与因子实验的个人平台：**机会 → 因子 → 投资 → 模拟交易**。

仓库：https://github.com/gaozhenxiao/lahm  
英文缩写：**lahm**（柳暗花明）

> **免责声明**：本项目仅供学习与研究，不构成任何投资建议；不提供实盘下单指令。市场有风险，决策需自负。

---

## 现在能做什么

| 模块 | 说明 |
|------|------|
| **因子列表** | 内置因子最新信号、回测摘要、净值图、操作历史 |
| **机会列表** | 跟踪当前可关注机会 |
| **投资列表** | 管理已跟踪标的 |
| **模拟交易** | 纸上交易演练 |
| **任务中心 / 报告** | 异步任务与报告查看 |
| **自选股 / 设置** | 行情关注与系统配置 |

侧栏已下线「学习中心 / 股票分析 / 股票筛选」入口（旧链接会跳回仪表板）。

### 内置因子

1. **国家队（`national_team`）**  
   观察汇金相关沪深 300 ETF 份额变化，按时代篮子配置仓位。  
   详见 [docs/features/guides/national_team.md](./docs/features/guides/national_team.md)

2. **暴跌抄底（`dip_buy`）**  
   急跌 + 估值分位闸门；交易 ETF：510300 / 159915 / 510500。  
   收盘调仓记账；空仓按约 1.4% 年化计息。  
   详见 [docs/features/guides/dip_buy.md](./docs/features/guides/dip_buy.md)

刷新与回测示例：

```bash
python scripts/refresh_national_team_data.py --backtest
python scripts/refresh_dip_buy_data.py --backtest
```

产物默认写在 `data/factors/`（已 gitignore）。

---

## 技术栈

- **后端**：FastAPI + Python 3.10+（包名 `lahm`）
- **前端**：Vue 3 + Element Plus（`frontend/`，包名 `lahm-frontend`）
- **数据**：MongoDB + Redis
- **行情**：akshare 等（因子脚本可独立跑）

环境变量前缀：`LAHM_*`（仍兼容旧的 `TRADINGAGENTS_*`）。  
默认库名：`lahm`。

---

## 快速开始

### 1. 克隆

```bash
git clone https://github.com/gaozhenxiao/lahm.git
cd lahm
```

私有仓库请先登录 GitHub（HTTPS Token 或 SSH）。

### 2. 环境

需要：

- Python ≥ 3.10  
- Node.js（前端开发）  
- MongoDB、Redis（本机或 Docker）

```bash
# 建议使用虚拟环境
python -m venv .venv

# Windows
.\.venv\Scripts\activate

# 安装后端依赖
pip install -e .

# 配置环境变量
copy .env.example .env
# 编辑 .env：填 Mongo/Redis、JWT、以及要用的大模型 API Key
```

前端：

```bash
cd frontend
npm install
npm run dev
```

后端开发启动（Windows 示例）：

```powershell
.\start_dev.ps1
```

常见本地地址：

- API：`http://localhost:8000`  
- 前端：`http://localhost:5173`  
- 默认管理员多为安装/初始化文档中的账号（请以你环境初始化结果为准，并尽快改密）

### 3. Docker（可选）

仓库内提供 `docker-compose.yml` 等编排文件，镜像/服务名已统一为 `lahm-*`。按 compose 注释启动即可。

---

## 目录速览

```
lahm/                 # Python 核心包（原 tradingagents 已更名）
app/                  # FastAPI 业务与路由
frontend/             # Vue 前端
scripts/              # 因子刷新、回测、运维脚本
docs/                 # 文档（含因子说明）
data/                 # 运行时数据（本地，不入库）
```

---

## 配置要点

| 项 | 说明 |
|----|------|
| `.env` | 从 `.env.example` 复制，**勿提交密钥** |
| `MONGODB_DATABASE` | 默认 `lahm`；旧库名需自行迁移 |
| `LAHM_*` | 日志目录、结果目录等 |

更细的配置见 `docs/` 与 `.env.example` 注释。

---

## 致谢

早期代码与多智能体分析框架思路，受益于开源项目  
[TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)。  
本仓库 **lahm / 柳暗花明** 为独立维护的分支产物，与原 TradingAgents-CN 发行线无运营关系。

---

## 许可与风险

请阅读仓库内 `LICENSE`、`COPYRIGHT.md` 等文件了解授权范围。  
分析结果与因子回测均为历史/模型输出，**不保证未来收益**，不构成投资建议。
