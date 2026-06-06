-- 排行榜查询合集（直接贴进 Grafana/Metabase 面板即可）。
-- 两路数据已统一在 usage_daily：source='api'(LiteLLM) + source='subscription'(客户端)。

-- 1) 总榜：最近 30 天，按人，含两路拆分
SELECT
    email,
    dept,
    SUM(total_tokens)                                          AS total_tokens,
    SUM(total_tokens) FILTER (WHERE source = 'api')            AS api_tokens,
    SUM(total_tokens) FILTER (WHERE source = 'subscription')   AS sub_tokens,
    ROUND(SUM(cost_usd), 2)                                    AS cost_usd
FROM usage_daily
WHERE usage_date >= current_date - 29
GROUP BY email, dept
ORDER BY total_tokens DESC
LIMIT 100;

-- 2) 部门榜
SELECT dept,
       SUM(total_tokens) AS total_tokens,
       ROUND(SUM(cost_usd), 2) AS cost_usd
FROM usage_daily
WHERE usage_date >= current_date - 29
GROUP BY dept
ORDER BY total_tokens DESC;

-- 3) 工具维度（claude_code / codex / cursor / litellm ...）
SELECT tool,
       SUM(total_tokens) AS total_tokens
FROM usage_daily
WHERE usage_date >= current_date - 29
GROUP BY tool
ORDER BY total_tokens DESC;

-- 4) 单人每日趋势（Grafana 用 $email 变量）
SELECT usage_date AS time, source, SUM(total_tokens) AS tokens
FROM usage_daily
WHERE email = '$email' AND usage_date >= current_date - 89
GROUP BY usage_date, source
ORDER BY usage_date;
