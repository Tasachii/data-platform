-- Latest version per order_id (source resends collapse, retro status updates win),
-- typed and timezone-normalized. Anything unusable is quarantined in
-- staging.rejected_orders with a reason instead of being silently dropped.

CREATE OR REPLACE TEMP VIEW _orders_latest AS
WITH parsed AS (
    SELECT
        order_id,
        customer_id,
        order_ts                                   AS order_ts_raw,
        total_amount                               AS total_amount_raw,
        TRY_CAST(order_ts AS TIMESTAMPTZ)          AS order_ts,
        TRY_CAST(updated_at AS TIMESTAMPTZ)        AS updated_at,
        lower(trim(status))                        AS status,
        TRY_CAST(total_amount AS DECIMAL(14, 2))   AS total_amount,
        lower(trim(channel))                       AS channel,
        _source_file,
        _ingested_at
    FROM raw.orders
)
SELECT *
FROM parsed
QUALIFY row_number() OVER (
    PARTITION BY order_id
    -- order_ts_raw as final key: source resends are NOT always byte-identical
    -- (same instant can arrive serialized in +07:00 on one copy and +00:00 on
    -- the other). Without a content tie-break the winner — and therefore the
    -- raw values we quarantine — flips randomly between runs.
    ORDER BY updated_at DESC NULLS LAST, _ingested_at DESC, order_ts_raw DESC
) = 1;

CREATE OR REPLACE TABLE staging.rejected_orders AS
SELECT
    order_id,
    customer_id,
    order_ts_raw,
    total_amount_raw,
    status,
    channel,
    _source_file,
    CASE
        WHEN order_id IS NULL                          THEN 'missing_order_id'
        WHEN order_ts IS NULL OR updated_at IS NULL    THEN 'unparseable_timestamp'
        WHEN total_amount IS NULL                      THEN 'amount_null_or_invalid'
        WHEN total_amount < 0                          THEN 'amount_negative'
    END AS reject_reason
FROM _orders_latest
WHERE order_id IS NULL
   OR order_ts IS NULL
   OR updated_at IS NULL
   OR total_amount IS NULL
   OR total_amount < 0;

CREATE OR REPLACE TABLE staging.stg_orders AS
SELECT
    order_id,
    customer_id,
    order_ts,
    updated_at,
    status,
    total_amount,
    channel,
    _source_file
FROM _orders_latest
WHERE order_id IS NOT NULL
  AND order_ts IS NOT NULL
  AND updated_at IS NOT NULL
  AND total_amount IS NOT NULL
  AND total_amount >= 0;
