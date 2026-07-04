-- Customers with email validity flagged, never dropped: a bad email is a
-- contactability problem, not a reason to lose the customer's orders.

CREATE OR REPLACE TABLE staging.stg_customers AS
SELECT
    customer_id,
    email,
    regexp_matches(email, '^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$') AS email_is_valid,
    TRY_CAST(signup_date AS DATE) AS signup_date,
    region
FROM raw.customers
WHERE customer_id IS NOT NULL;
