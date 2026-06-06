# 企业 Agent Token 消耗排行榜

汇总主流 AI 编码 agent（Claude Code / Codex / Cursor / Gemini CLI 等）的 token 消耗，
做个人/部门排行榜。**两路数据都采集**：

| 来源 | 覆盖 | 采集方式 |
|---|---|---|
| `source='api'` | 走 LiteLLM 的 API key 流量（有真实 $） | 收集端定时拉 LiteLLM `/spend/logs` |
| `source='subscription'` | 订阅制登录（Claude Pro/Max、Codex 订阅等，**不经过 LiteLLM**） | 每台 Mac 用 [tokscale](https://github.com/junhoyeo/tokscale) 读本地日志后上报 |

两路统一落到 Postgres 同一张表 `usage_daily`，看板里合并出榜。cc-switch 保持不动，继续管配置切换。

```
每台 Mac (飞连下发):  tokscale --json ──> tokreport.py ──HTTPS──┐
                                                                ├─> collector ─> Postgres ─> Grafana 排行榜
LiteLLM ──(litellm_sync.py 定时拉)──────────────────────────────┘
```

## 目录

```
collector/   收集端：FastAPI + Postgres + LiteLLM 同步脚本（docker-compose 一键起）
agent/       客户端 sidecar：tokreport.py + launchd plist + 配置模板 + 飞连安装脚本
dashboard/   排行榜 SQL + Grafana 面板 JSON
```

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

## 2. 下发客户端（飞连 MDM）

打一个下发包，含 4 个文件：`tokscale`(pin 版本二进制)、`tokreport.py`、
`com.eggyrooch.tokreport.plist`、`tokreport.conf`（**按设备填好 EMPLOYEE_EMAIL/DEPT**）。

飞连以 root 执行：
```bash
sudo ./install.sh <下发包目录>
```
脚本会把二进制/脚本装好、配置写到 `/etc/tokreport.conf`、并在**登录用户的用户域**加载
LaunchAgent（必须用户域才能读到该用户的 `~/.claude`、`~/.codex`）。每天 19:00 自动上报。

手动验证一次：
```bash
TOKREPORT_CONF=/etc/tokreport.conf python3 /usr/local/bin/tokreport.py
curl -H "Authorization: Bearer <token>" "https://<collector>/v1/leaderboard?days=7"
```

## 3. 看板

Grafana 加 Postgres 数据源后导入 `dashboard/grafana-dashboard.json`，
或直接用 `dashboard/leaderboard.sql` 里的查询。

## 落地注意事项（重要）

- **身份归属是排行榜的根**：靠飞连按设备把 `EMPLOYEE_EMAIL` 写进 `/etc/tokreport.conf`。
  也可改成上报 `device_id`、由收集端 `device_identity` 表 JOIN 出 email。
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
