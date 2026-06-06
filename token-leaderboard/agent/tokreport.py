#!/usr/bin/env python3
"""客户端上报：用 tokscale 读本地各 agent 日志(订阅制用量也在内)，按天上报到收集端。

只依赖 python3 标准库 + tokscale 二进制。由 launchd 每天定时触发。
幂等：每次重传最近 LOOKBACK_DAYS 天，收集端按 (email,date,source,tool,model) 覆盖。

注意：只上报 token 计数/成本，绝不读取或上传 prompt / 代码内容。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from datetime import date, timedelta

CONF_PATH = os.environ.get("TOKREPORT_CONF", "/etc/tokreport.conf")


def load_conf(path: str) -> dict:
    conf: dict[str, str] = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            conf[k.strip()] = v.strip().strip('"')
    return conf


def run_tokscale(binary: str, day: date) -> list[dict]:
    """取某一天的用量。tokscale 不同版本 JSON 结构略有差异，归一化集中在 normalize()。"""
    out = subprocess.run(
        [binary, "--json", "--since", day.isoformat(), "--until", day.isoformat()],
        capture_output=True, text=True, check=True,
    ).stdout
    return normalize(json.loads(out), day)


def _num(d: dict, *keys: str) -> int:
    for k in keys:
        if k in d and d[k] is not None:
            try:
                return int(d[k])
            except (TypeError, ValueError):
                pass
    return 0


def normalize(payload, day: date) -> list[dict]:
    """把 tokscale JSON 拍平成 [{usage_date, tool, model, *_tokens, cost_usd}]。
    兼容几种常见结构：顶层 list / {"records":[...]} / {"clients":[...]}。
    若你的 tokscale 版本字段名不同，改这里即可。"""
    if isinstance(payload, dict):
        rows = payload.get("records") or payload.get("clients") or payload.get("data") or []
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []

    records = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        tool = r.get("client") or r.get("tool") or r.get("agent") or "unknown"
        model = r.get("model") or "unknown"
        rec = {
            "usage_date": day.isoformat(),
            "tool": str(tool),
            "model": str(model),
            "input_tokens": _num(r, "input_tokens", "inputTokens", "input"),
            "output_tokens": _num(r, "output_tokens", "outputTokens", "output"),
            "cache_read_tokens": _num(r, "cache_read_tokens", "cacheReadTokens", "cache_read"),
            "cache_write_tokens": _num(r, "cache_write_tokens", "cache_creation_tokens",
                                       "cacheCreationTokens", "cache_write"),
            "total_tokens": _num(r, "total_tokens", "totalTokens", "tokens"),
            "cost_usd": float(r.get("cost") or r.get("cost_usd") or 0.0),
        }
        if any(rec[k] for k in ("input_tokens", "output_tokens", "cache_read_tokens",
                                "cache_write_tokens", "total_tokens")):
            records.append(rec)
    return records


def post(conf: dict, records: list[dict]) -> None:
    body = json.dumps({
        "email": conf["EMPLOYEE_EMAIL"],
        "dept": conf.get("DEPT", "unknown"),
        "source": "subscription",
        "records": records,
    }).encode()
    req = urllib.request.Request(
        conf["COLLECTOR_URL"].rstrip("/") + "/v1/usage/report",
        data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {conf['COLLECTOR_TOKEN']}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()


def main() -> int:
    conf = load_conf(CONF_PATH)
    binary = conf.get("TOKSCALE_BIN", "/usr/local/bin/tokscale")
    lookback = int(conf.get("LOOKBACK_DAYS", "3"))

    all_records: list[dict] = []
    for i in range(lookback):
        day = date.today() - timedelta(days=i)
        try:
            all_records.extend(run_tokscale(binary, day))
        except subprocess.CalledProcessError as e:
            print(f"tokscale failed for {day}: {e.stderr}", file=sys.stderr)

    if not all_records:
        print("no usage to report")
        return 0
    post(conf, all_records)
    print(f"reported {len(all_records)} records as {conf['EMPLOYEE_EMAIL']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
