# 企业 Agent Token 消耗排行榜

汇总主流 AI 编码 agent（Claude Code / Codex / Cursor / Gemini CLI 等）的 token 消耗，
做个人/部门排行榜。**两路数据都采集**：

| 来源 | 覆盖 | 采集方式 |
|---|---|---|
| `source='api'` | 走 LiteLLM 的 API key 流量（有真实 $） | 收集端定时拉 LiteLLM `/spend/logs` |
| `source='subscription'` | 订阅制登录（Claude Pro/Max、Codex 订阅等，**不经过 LiteLLM**） | 每台 Mac 用 [tokscale](https://github.com/junhoyeo/tokscale) 读本地日志后上报 |

两路统一落到 Postgres 同一张表 `usage_daily`，看板里合并出榜。cc-switch 保持不动，继续管配置切换。

> **通用性 / 扩展性**：不绑定飞连/MDM（提供免 root 自助安装）、员工弱感知/无感知（身份自动解析、后台静默）、
> 采集源与身份均可插拔。设计与扩展点见 [`ARCHITECTURE.md`](ARCHITECTURE.md)。
>
> **大厂参考（Meta）**：借鉴 Scribe 解耦 ingest、Scuba/Hive 热冷分层、PAI 按目的治理；
> 并刻意**不做个人监控式排行榜**（默认团队维度）。见 [`BIG-TECH-PATTERNS.md`](BIG-TECH-PATTERNS.md)。
>
> **代码产出指标**：除 token 量外，还可统计 AI 代码**采纳率 / 有效代码行数**
> （Cursor Admin API + Claude Code OTEL + git 存活分析），同架构第二指标族，见 [`CODE-METRICS.md`](CODE-METRICS.md)。

```
每台 Mac (飞连下发):  tokscale --json ──> tokreport.py ──HTTPS──┐
                                                                ├─> collector ─> Postgres ─> Grafana 排行榜
LiteLLM ──(litellm_sync.py 定时拉)──────────────────────────────┘
```

## 目录

```
collector/   收集端：FastAPI + Postgres + 自带看板(/) + LiteLLM/Cursor 同步脚本（compose 一键起）
agent/       客户端 sidecar：tokreport.py + 可插拔采集源 + launchd plist + MDM/自助安装 + 打包脚本
dashboard/   排行榜 SQL + Grafana 面板 JSON（进阶；MVP 用收集端自带看板即可）
```

## MVP 快速验收（5 分钟，先看到东西再铺开）

```bash
cd collector
cp .env.example .env                          # 至少设 COLLECTOR_API_TOKENS=devtoken
docker compose up -d                          # 起 postgres + collector(:8088) + grafana(:3000)
COLLECTOR_URL=http://localhost:8088 COLLECTOR_TOKEN=devtoken python seed_demo.py   # 灌样例数据
open http://localhost:8088/                    # ← 自带看板：个人/部门 Token 榜 + 采纳率，无需 Grafana
```
看板这一路是**实测跑通**的（ingest → Postgres → `/` 看板，幂等 upsert 已验证）。确认没问题后，
按下面「下发客户端」把真实数据通过 MDM 接进来；`seed_demo.py` 仅用于演示，正式环境不用。

## 1. 起收集端

```bash
cd collector
cp .env.example .env        # 填 COLLECTOR_API_TOKENS / LITELLM_* 等
docker compose up -d        # 起 postgres + collector(:8088) + grafana(:3000)
```
> 已有 Grafana/Postgres 可删掉 compose 里对应 service，把 collector 的 `DATABASE_URL` 指到你的库。

LiteLLM 同步（建一个每天的 cron / k8s CronJob）：
```bash
DATABASE_URL=... LITELLM_BASE_URL=... LITELLM_MASTER_KEY=... python litellm_sync.py
```

## 2. 下发客户端（三选一，不绑定 MDM）

客户端是**可插拔采集源 + 自动身份解析**的 sidecar，员工弱感知/无感知。详见
[`ARCHITECTURE.md`](ARCHITECTURE.md)。身份按优先级自动取：MDM 下发的 `EMPLOYEE_EMAIL`
→ `git config user.email`（零输入自动归属）→ 登录名@域名。

**A. 有 MDM / 飞连**（root，按设备下发身份，最稳）—— **MVP 主路径**
```bash
# 1) 在你的机器上一键打包（含 tokscale 二进制 + 已填好的 conf）：
agent/package_mdm.sh ./tokscale https://<collector> <token> ./dist
# 2) 把 dist/tokreport-mdm.tar.gz 交给飞连/JAMF 下发，目标机解包后以 root 执行：
sudo ./install.sh .
```
脚本会装好程序+二进制(自动过 Gatekeeper)、写 `/etc/tokreport.conf`、在用户域加载 LaunchAgent
（每天 19:00 静默上报）。身份留空则自动用 git email，无需逐台填。

**B. 没有 MDM**（免 root，员工执行一次，之后静默后台跑）
```bash
curl -fsSL https://intranet/tok/bootstrap.sh | \
  COLLECTOR_URL=https://<collector> COLLECTOR_TOKEN=xxx BASE_URL=https://intranet/tok bash
```
默认用 `claude_code` 采集源（**免分发二进制**）；想用 tokscale 覆盖全量工具，加 `COLLECTORS=tokscale`。

**C. 随装机/ dotfiles 捆绑**：把 B 的步骤并进你现有的开发环境初始化脚本即可。

> 采集源由 `COLLECTORS=` 控制（`tokscale` 一把覆盖 25+ 工具，需二进制；`claude_code` 零依赖）。
> 加新工具只需在 `agent/collectors/` 写一个类并登记，见 ARCHITECTURE.md。

手动验证一次：
```bash
TOKREPORT_CONF=/etc/tokreport.conf python3 /usr/local/lib/tokreport/tokreport.py
curl -H "Authorization: Bearer <token>" "https://<collector>/v1/leaderboard?days=7"
```

## 3. 看板（展示）

- **最简（MVP）**：直接打开收集端自带看板 **`http://<collector>:8088/`** —— 个人/部门 Token 榜、
  工具维度、代码采纳率，零额外部署。`?days=7|30|90` 切换窗口。
- **进阶**：`docker compose` 已自动给 Grafana 挂好数据源与面板（`:3000`，admin/admin）；
  或手动用 `dashboard/leaderboard.sql` 里的查询自建。

## 落地注意事项（重要）

- **身份归属是排行榜的根**：自动解析（MDM 下发 `EMPLOYEE_EMAIL` → `git config user.email` →
  登录名@域名），没有 MDM 也能零输入归属；逻辑集中在 `agent/identity.py`，想换 SSO/`device_id` 只改这一处。
- **幂等**：客户端每次重传最近 `LOOKBACK_DAYS` 天、LiteLLM 同样回看几天，
  收集端按 `(email,date,source,tool,model)` upsert，离线补传/重复跑都不会重复计数。
- **隐私合规**：只采集 token 计数/成本/模型/时间，**不读取也不上传 prompt 或代码**。上线前与安全/法务对齐。
- **不要用 `tokscale submit`**：那是上传到 *公共* 排行榜；本方案只用它的 `--json` 当本地解析器。
- **版本差异**：tokscale 与 LiteLLM 的 JSON 字段在不同版本会变，解析分别集中在
  `agent/tokreport.py: normalize()` 和 `collector/litellm_sync.py: _parse_log()`，按你装的版本对一下字段名即可。
- **Cursor 特例**：tokscale 读 Cursor 需要从 Cursor API 同步缓存（要登录态）；
  纯本地 JSONL 的 Claude Code / Codex 开箱即用。Codex 的 token 计数仅 2025-09 之后的日志才有。
- **去重边界**：若同一个人既走订阅又走 LiteLLM，两路会分别计入 `subscription` 与 `api`，
  总榜是两者之和（符合预期）；想只看其一，按 `source` 过滤即可。
