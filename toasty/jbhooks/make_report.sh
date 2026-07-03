sqlite3 -csv -header tip_distribution.db <<'EOF' > tip_report.csv
WITH DailyActivities AS (
    SELECT
        substr(s.date, 7, 4) || '-' || substr(s.date, 1, 2) || '-' || substr(s.date, 4, 2) AS "Date",
        s.server AS "Worker",
        'Server' AS "Job Title",
        s.cash_tips AS "Cash Tips",
        s.non_cash_tips AS "Non-Cash Tips",
        s.gratuity AS "Gratuity",
        s.sum_tips_for_payout AS "Tips Paid Out",
        s.net_sales AS "Net Sales",
        0 AS "Tips Received"
    FROM
        servers s
    UNION ALL
    SELECT
        substr(b.date, 7, 4) || '-' || substr(b.date, 1, 2) || '-' || substr(b.date, 4, 2) AS "Date",
        b.bartender AS "Worker",
        'Bartender' AS "Job Title",
        b.cash_tips AS "Cash Tips",
        b.credit_tips AS "Non-Cash Tips",
        0 AS "Gratuity",
        b.sum_tips_for_payout AS "Tips Paid Out",
        b.net_sales AS "Net Sales",
        0 AS "Tips Received"
    FROM
        bartenders b
    UNION ALL
    SELECT
        date(c.timestamp) AS "Date",
        c.worker_name AS "Worker",
        REPLACE(c.reason, ' payout', '') AS "Job Title",
        0, 0, 0, 0, 0, -- Set non-applicable columns to zero
        ABS(c.amount) AS "Tips Received"
    FROM
        cashbox_ledger c
    WHERE
        c.reason LIKE '%payout' AND c.amount < 0
)
SELECT
    "Date",
    "Worker",
    "Job Title",
    ROUND(SUM("Cash Tips"), 2) AS "Cash Tips",
    ROUND(SUM("Non-Cash Tips"), 2) AS "Non-Cash Tips",
    ROUND(SUM("Gratuity"), 2) AS "Gratuity",
    ROUND(SUM("Tips Paid Out"), 2) AS "Tips Paid Out",
    ROUND(SUM("Net Sales"), 2) AS "Net Sales",
    ROUND(SUM("Tips Received"), 2) AS "Tips Received",
    CASE
        WHEN SUM("Net Sales") > 0 THEN ROUND(
            (SUM("Cash Tips") + SUM("Non-Cash Tips") + SUM("Gratuity")) * 100.0 / SUM("Net Sales"),
            2
        )
        ELSE 0
    END AS "Tip % of Sales"
FROM
    DailyActivities
GROUP BY
    "Date",
    "Worker",
    "Job Title"
ORDER BY
    "Date" DESC,
    "Worker",
    "Job Title";
EOF
