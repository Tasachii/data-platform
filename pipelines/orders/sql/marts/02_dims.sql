-- Dimensions. dim_customers carries an explicit 'unknown' member so facts can
-- keep referential integrity even for orphan customer_ids.

CREATE OR REPLACE TABLE marts.dim_customers AS
SELECT
    customer_id,
    email,
    email_is_valid,
    signup_date,
    region
FROM staging.stg_customers
UNION ALL
SELECT
    'unknown', NULL, false, NULL, NULL;

CREATE OR REPLACE TABLE marts.dim_products AS
SELECT
    product_id,
    name,
    category,
    cost
FROM staging.stg_products;
