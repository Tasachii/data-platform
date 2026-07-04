-- Typed order lines, exact resend duplicates collapsed via DISTINCT.

CREATE OR REPLACE TABLE staging.stg_order_items AS
SELECT DISTINCT
    order_id,
    product_id,
    TRY_CAST(qty AS INTEGER)                AS qty,
    TRY_CAST(unit_price AS DECIMAL(12, 2))  AS unit_price
FROM raw.order_items
WHERE order_id IS NOT NULL
  AND TRY_CAST(qty AS INTEGER) > 0
  AND TRY_CAST(unit_price AS DECIMAL(12, 2)) >= 0;
