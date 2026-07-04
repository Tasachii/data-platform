CREATE OR REPLACE TABLE staging.stg_products AS
SELECT
    product_id,
    name,
    category,
    TRY_CAST(cost AS DECIMAL(12, 2)) AS cost
FROM raw.products
WHERE product_id IS NOT NULL;
