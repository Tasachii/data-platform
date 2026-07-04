-- SCD Type 2 over order status: every (order_id, status, updated_at) version
-- becomes a validity interval. Retroactive refunds show up as a second row;
-- exact resends collapse under DISTINCT because their updated_at is identical.

CREATE OR REPLACE TABLE intermediate.int_order_status_history AS
WITH versions AS (
    SELECT DISTINCT
        order_id,
        lower(trim(status))                 AS status,
        TRY_CAST(updated_at AS TIMESTAMPTZ) AS updated_at
    FROM raw.orders
    WHERE order_id IS NOT NULL
      AND TRY_CAST(updated_at AS TIMESTAMPTZ) IS NOT NULL
)
SELECT
    order_id,
    status,
    updated_at                                   AS valid_from,
    lead(updated_at) OVER w                      AS valid_to,
    lead(updated_at) OVER w IS NULL              AS is_current
FROM versions
WINDOW w AS (PARTITION BY order_id ORDER BY updated_at)
ORDER BY order_id, valid_from;
