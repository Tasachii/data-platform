"""Waterfall matching engine: gateway transactions vs internal ledger.

Every gateway txn and every ledger entry ends in EXACTLY ONE bucket:

    rule 1  exact              ref + amount + UTC date all agree
    rule 2  date_boundary      ref + amount agree, settlement crossed midnight
    rule 3  fee_timing         ref agrees, ledger already net of the fee
            rounding           ref agrees, |diff| <= 0.05
            amount_other       ref agrees, unexplained amount difference
    rule 4  possible_ref_issue amount + date agree but refs don't (fuzzy, 1:1)
    rule 5  missing_in_ledger / missing_in_gateway   (residuals)
    pre     duplicate_posting  same (ref, amount) posted twice in the ledger

Normalization first, matching second: refs are upper-trimmed and stripped of
the "GW-" prefix, currencies upper-trimmed, timestamps parsed to UTC instants,
amounts DECIMAL. Matching on raw strings is how real recon breaks.

The engine takes any DuckDB connection so unit tests can run it on tiny
in-memory fixtures.
"""

from __future__ import annotations

import duckdb

from pipelines.orders.common import connect, get_logger

log = get_logger("recon.matching")

ROUNDING_TOLERANCE = 0.05
FEE_TOLERANCE = 0.005

# Alert thresholds (spec): matched% of gateway txns, absolute THB gap, dup count.
MATCH_RATE_CRITICAL_BELOW = 97.0
NET_DIFF_CRITICAL_ABOVE = 10_000.0


def run_matching(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("CREATE SCHEMA IF NOT EXISTS recon")

    log.info("normalizing both sources")
    con.execute("""
        CREATE OR REPLACE TABLE recon.norm_gateway AS
        SELECT
            txn_id,
            regexp_replace(upper(trim(gateway_ref)), '^GW-', '') AS ref,
            TRY_CAST(amount AS DECIMAL(14, 2))                   AS amount,
            upper(trim(currency))                                AS currency,
            TRY_CAST(fee AS DECIMAL(14, 2))                      AS fee,
            CAST(timezone('UTC', TRY_CAST(created_at AS TIMESTAMPTZ)) AS DATE) AS txn_date
        FROM raw.gateway_txns
    """)
    con.execute("""
        CREATE OR REPLACE TABLE recon.norm_ledger AS
        SELECT
            entry_id,
            regexp_replace(upper(trim(external_ref)), '^GW-', '') AS ref,
            TRY_CAST(amount AS DECIMAL(14, 2))                    AS amount,
            upper(trim(currency))                                 AS currency,
            CAST(timezone('UTC', TRY_CAST(posted_at AS TIMESTAMPTZ)) AS DATE) AS entry_date,
            -- second posting of the same (ref, amount) = duplicate
            row_number() OVER (PARTITION BY ref, amount ORDER BY entry_id) AS posting_seq
        FROM raw.ledger_entries
    """)

    log.info("running waterfall")
    con.execute(f"""
        CREATE OR REPLACE TABLE recon.recon_results AS
        WITH ledger_canon AS (
            SELECT * FROM recon.norm_ledger WHERE posting_seq = 1
        ),

        rule1 AS (
            SELECT g.txn_id, l.entry_id, g.ref, g.amount AS gateway_amount,
                   l.amount AS ledger_amount, g.txn_date,
                   'exact' AS match_type, 1.00 AS match_confidence
            FROM recon.norm_gateway g
            JOIN ledger_canon l
              ON g.ref = l.ref AND g.amount = l.amount AND g.txn_date = l.entry_date
        ),

        rule2 AS (
            SELECT g.txn_id, l.entry_id, g.ref, g.amount, l.amount, g.txn_date,
                   'date_boundary', 0.95
            FROM recon.norm_gateway g
            JOIN ledger_canon l ON g.ref = l.ref AND g.amount = l.amount
            WHERE g.txn_id NOT IN (SELECT txn_id FROM rule1)
              AND l.entry_id NOT IN (SELECT entry_id FROM rule1)
        ),

        rule3 AS (
            SELECT g.txn_id, l.entry_id, g.ref, g.amount, l.amount, g.txn_date,
                   CASE
                       WHEN abs((g.amount - l.amount) - g.fee) < {FEE_TOLERANCE}
                           THEN 'fee_timing'
                       WHEN abs(g.amount - l.amount) <= {ROUNDING_TOLERANCE}
                           THEN 'rounding'
                       ELSE 'amount_other'
                   END,
                   0.80
            FROM recon.norm_gateway g
            JOIN ledger_canon l ON g.ref = l.ref
            WHERE g.txn_id NOT IN (SELECT txn_id FROM rule1 UNION ALL SELECT txn_id FROM rule2)
              AND l.entry_id NOT IN (SELECT entry_id FROM rule1 UNION ALL SELECT entry_id FROM rule2)
        ),

        matched_so_far AS (
            SELECT txn_id, entry_id FROM rule1
            UNION ALL SELECT txn_id, entry_id FROM rule2
            UNION ALL SELECT txn_id, entry_id FROM rule3
        ),

        -- rule 4: same money on the same day, refs disagree. Greedy 1:1 by
        -- rank within each (amount, date) group so one entry never matches twice.
        g_left AS (
            SELECT *, row_number() OVER (PARTITION BY amount, txn_date ORDER BY txn_id) AS rn
            FROM recon.norm_gateway
            WHERE txn_id NOT IN (SELECT txn_id FROM matched_so_far)
        ),
        l_left AS (
            SELECT *, row_number() OVER (PARTITION BY amount, entry_date ORDER BY entry_id) AS rn
            FROM ledger_canon
            WHERE entry_id NOT IN (SELECT entry_id FROM matched_so_far)
        ),
        rule4 AS (
            SELECT g.txn_id, l.entry_id, g.ref, g.amount, l.amount, g.txn_date,
                   'possible_ref_issue', 0.50
            FROM g_left g
            JOIN l_left l
              ON g.amount = l.amount AND g.txn_date = l.entry_date AND g.rn = l.rn
            -- refs must actually look related: same money on the same day is
            -- one accidental collision per ~100k txns (observed), and pairing
            -- two genuinely-missing records hides BOTH from the finance team
             AND (contains(g.ref, l.ref) OR contains(l.ref, g.ref)
                  OR levenshtein(g.ref, l.ref) <= 4)
        ),

        all_matched AS (
            SELECT * FROM rule1
            UNION ALL SELECT * FROM rule2
            UNION ALL SELECT * FROM rule3
            UNION ALL SELECT * FROM rule4
        ),

        rule5_gateway AS (
            SELECT g.txn_id, NULL AS entry_id, g.ref, g.amount, NULL, g.txn_date,
                   'missing_in_ledger', 1.00
            FROM recon.norm_gateway g
            WHERE g.txn_id NOT IN (SELECT txn_id FROM all_matched)
        ),
        rule5_ledger AS (
            SELECT NULL, l.entry_id, l.ref, NULL, l.amount, l.entry_date,
                   'missing_in_gateway', 1.00
            FROM ledger_canon l
            WHERE l.entry_id NOT IN (SELECT entry_id FROM all_matched)
        ),
        dup_postings AS (
            SELECT NULL, l.entry_id, l.ref, NULL, l.amount, l.entry_date,
                   'duplicate_posting', 1.00
            FROM recon.norm_ledger l
            WHERE l.posting_seq > 1
        )

        SELECT txn_id, entry_id, ref,
               gateway_amount, ledger_amount,
               COALESCE(gateway_amount, 0) - COALESCE(ledger_amount, 0) AS amount_diff,
               txn_date,
               match_type, match_confidence
        FROM (
            SELECT * FROM all_matched
            UNION ALL SELECT * FROM rule5_gateway
            UNION ALL SELECT * FROM rule5_ledger
            UNION ALL SELECT * FROM dup_postings
        )
    """)

    log.info("building daily summary")
    con.execute("""
        CREATE OR REPLACE TABLE recon.recon_summary AS
        WITH gateway_daily AS (
            SELECT txn_date, count(*) AS gateway_count, SUM(amount) AS gateway_amount
            FROM recon.norm_gateway GROUP BY txn_date
        ),
        ledger_daily AS (
            SELECT entry_date AS txn_date, count(*) AS ledger_count, SUM(amount) AS ledger_amount
            FROM recon.norm_ledger GROUP BY entry_date
        ),
        buckets AS (
            SELECT txn_date,
                count(*) FILTER (WHERE match_type IN ('exact', 'date_boundary'))         AS matched,
                count(*) FILTER (WHERE match_type = 'fee_timing')                        AS fee_timing,
                count(*) FILTER (WHERE match_type = 'rounding')                          AS rounding,
                count(*) FILTER (WHERE match_type = 'amount_other')                      AS amount_other,
                count(*) FILTER (WHERE match_type = 'possible_ref_issue')                AS possible_ref_issue,
                count(*) FILTER (WHERE match_type = 'missing_in_ledger')                 AS missing_in_ledger,
                count(*) FILTER (WHERE match_type = 'missing_in_gateway')                AS missing_in_gateway,
                count(*) FILTER (WHERE match_type = 'duplicate_posting')                 AS duplicate_posting
            FROM recon.recon_results GROUP BY txn_date
        )
        SELECT
            g.txn_date,
            g.gateway_count, g.gateway_amount,
            COALESCE(l.ledger_count, 0)  AS ledger_count,
            COALESCE(l.ledger_amount, 0) AS ledger_amount,
            b.matched, b.fee_timing, b.rounding, b.amount_other,
            b.possible_ref_issue, b.missing_in_ledger, b.missing_in_gateway,
            b.duplicate_posting,
            ROUND(100.0 * (b.matched + b.fee_timing + b.rounding + b.possible_ref_issue)
                  / g.gateway_count, 2)                          AS match_rate_pct,
            g.gateway_amount - COALESCE(l.ledger_amount, 0)      AS net_difference
        FROM gateway_daily g
        LEFT JOIN ledger_daily l USING (txn_date)
        LEFT JOIN buckets b USING (txn_date)
        ORDER BY g.txn_date
    """)


def evaluate_alerts(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    """Write alert rows and return them: (txn_date, severity, rule, detail)."""
    con.execute("""
        CREATE OR REPLACE TABLE recon.alerts AS
        SELECT txn_date, 'CRITICAL' AS severity, 'match_rate' AS rule,
               'match rate ' || match_rate_pct || '% below threshold' AS detail
        FROM recon.recon_summary WHERE match_rate_pct < ?

        UNION ALL
        SELECT txn_date, 'CRITICAL', 'net_difference',
               'net difference ' || ROUND(net_difference, 2) || ' THB exceeds threshold'
        FROM recon.recon_summary WHERE abs(net_difference) > ?

        UNION ALL
        SELECT txn_date, 'WARNING', 'duplicate_posting',
               duplicate_posting || ' duplicate ledger postings'
        FROM recon.recon_summary WHERE duplicate_posting > 0
    """, [MATCH_RATE_CRITICAL_BELOW, NET_DIFF_CRITICAL_ABOVE])
    alerts = con.execute("SELECT * FROM recon.alerts ORDER BY txn_date, severity").fetchall()
    for txn_date, severity, rule, detail in alerts:
        log.warning("ALERT [%s] %s %s: %s", severity, txn_date, rule, detail)
    return alerts


def run(con: duckdb.DuckDBPyConnection | None = None) -> list[tuple]:
    own = con is None
    if own:
        con = connect()
    try:
        run_matching(con)
        return evaluate_alerts(con)
    finally:
        if own:
            con.close()


if __name__ == "__main__":
    run()
