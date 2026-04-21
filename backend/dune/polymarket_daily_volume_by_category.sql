WITH market_categories AS (
  SELECT
    unique_key,
    CASE
      WHEN tags IS NULL OR TRIM(tags) = '' THEN 'Other'
      WHEN REGEXP_LIKE(LOWER(tags), 'sports|nba|nfl|nhl|mlb|soccer|football|boxing|mma|tennis|f1|golf|ufc') THEN 'Sports'
      WHEN REGEXP_LIKE(LOWER(tags), 'crypto|bitcoin|btc|ethereum|eth|solana|defi|xrp|doge|token') THEN 'Crypto'
      WHEN REGEXP_LIKE(LOWER(tags), 'politics|election|trump|biden|congress|senate|president|white house') THEN 'Politics'
      WHEN REGEXP_LIKE(LOWER(tags), 'entertainment|celebrity|celebrities|movie|movies|music|tv|award|oscar|grammy') THEN 'Entertainment'
      WHEN REGEXP_LIKE(LOWER(tags), 'economy|economics|fed|inflation|gdp|cpi|recession|unemployment|macro') THEN 'Economy'
      ELSE 'Other'
    END AS category
  FROM polymarket_polygon.market_details
  WHERE unique_key IS NOT NULL
),
cat_deduped AS (
  SELECT unique_key, category
  FROM (
    SELECT
      unique_key,
      category,
      ROW_NUMBER() OVER (
        PARTITION BY unique_key
        ORDER BY CASE category
          WHEN 'Sports' THEN 1
          WHEN 'Crypto' THEN 2
          WHEN 'Politics' THEN 3
          WHEN 'Entertainment' THEN 4
          WHEN 'Economy' THEN 5
          ELSE 9
        END
      ) AS rn
    FROM market_categories
  )
  WHERE rn = 1
)
SELECT
  CAST(DATE_TRUNC('day', t.block_time) AS DATE) AS day,
  COALESCE(c.category, 'Other') AS category,
  SUM(t.amount) AS daily_volume_usd
FROM polymarket_polygon.market_trades t
LEFT JOIN cat_deduped c
  ON t.unique_key = c.unique_key
WHERE t.action = 'CLOB trade'
  AND t.block_month >= DATE '2024-01-01'
  AND t.block_time >= TIMESTAMP '2024-01-01 00:00:00'
  AND t.block_time < CAST(CURRENT_DATE AS TIMESTAMP)
GROUP BY 1, 2
ORDER BY 1 DESC, 2
