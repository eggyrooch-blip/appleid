"""中心收集端：接收客户端(订阅制)上报 + 提供排行榜查询。

设计要点：
- POST /v1/usage/report 做幂等 upsert，主键 (email, usage_date, source, tool, model)。
- 鉴权用 Bearer token（COLLECTOR_API_TOKENS，逗号分隔，可给不同部门发不同 token）。
- LiteLLM 那一路由 litellm_sync.py 单独灌入同一张表(source='api')，所以这里不耦合 LiteLLM。
- 只接收 token 计数/成本，绝不接收 prompt 或代码内容。
"""
from __future__ import annotations

import os
from datetime import date
from typing import List, Optional

import asyncpg
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

DATABASE_URL = os.environ["DATABASE_URL"]
API_TOKENS = {t.strip() for t in os.environ.get("COLLECTOR_API_TOKENS", "").split(",") if t.strip()}

app = FastAPI(title="Token Leaderboard Collector", version="1.0.0")
_pool: Optional[asyncpg.Pool] = None


@app.on_event("startup")
async def _startup() -> None:
    global _pool
    _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    with open(os.path.join(os.path.dirname(__file__), "schema.sql")) as fh:
        async with _pool.acquire() as conn:
            await conn.execute(fh.read())


def require_token(authorization: str = Header(default="")) -> None:
    if not API_TOKENS:  # 未配置 token 时拒绝启动式保护
        raise HTTPException(500, "collector has no API tokens configured")
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    if authorization.split(" ", 1)[1] not in API_TOKENS:
        raise HTTPException(403, "invalid token")


class UsageRecord(BaseModel):
    usage_date: date
    tool: str
    model: str = "unknown"
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0


class ReportPayload(BaseModel):
    email: str
    dept: str = "unknown"
    source: str = Field(default="subscription", pattern="^(subscription|api)$")
    records: List[UsageRecord]


UPSERT = """
INSERT INTO usage_daily (email, dept, usage_date, source, tool, model,
    input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
    total_tokens, cost_usd, updated_at)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12, now())
ON CONFLICT (email, usage_date, source, tool, model) DO UPDATE SET
    dept=EXCLUDED.dept,
    input_tokens=EXCLUDED.input_tokens,
    output_tokens=EXCLUDED.output_tokens,
    cache_read_tokens=EXCLUDED.cache_read_tokens,
    cache_write_tokens=EXCLUDED.cache_write_tokens,
    total_tokens=EXCLUDED.total_tokens,
    cost_usd=EXCLUDED.cost_usd,
    updated_at=now();
"""


@app.post("/v1/usage/report", dependencies=[Depends(require_token)])
async def report(payload: ReportPayload) -> dict:
    assert _pool is not None
    async with _pool.acquire() as conn:
        async with conn.transaction():
            for r in payload.records:
                total = r.total_tokens or (
                    r.input_tokens + r.output_tokens + r.cache_read_tokens + r.cache_write_tokens
                )
                await conn.execute(
                    UPSERT, payload.email, payload.dept, r.usage_date, payload.source,
                    r.tool, r.model, r.input_tokens, r.output_tokens, r.cache_read_tokens,
                    r.cache_write_tokens, total, r.cost_usd,
                )
    return {"ok": True, "upserted": len(payload.records)}


@app.get("/v1/leaderboard", dependencies=[Depends(require_token)])
async def leaderboard(days: int = 30, source: str = "all", limit: int = 100) -> dict:
    assert _pool is not None
    where_source = "" if source == "all" else "AND source = $2"
    args: list = [days]
    if source != "all":
        args.append(source)
    args.append(limit)
    sql = f"""
        SELECT email, dept,
               SUM(total_tokens) AS total_tokens,
               SUM(cost_usd)     AS cost_usd
        FROM usage_daily
        WHERE usage_date >= current_date - ($1::int - 1)
        {where_source}
        GROUP BY email, dept
        ORDER BY total_tokens DESC
        LIMIT ${len(args)};
    """
    async with _pool.acquire() as conn:
        rows = await conn.fetch(sql, *args)
    return {"days": days, "source": source,
            "ranking": [dict(r) for r in rows]}


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}
