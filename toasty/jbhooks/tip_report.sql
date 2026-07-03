-- =================================================================================
-- Detailed Worker Report Query (CTE Version)
--
-- This query has been updated to consolidate all of a worker's daily activities 
-- into a single, comprehensive row to improve clarity.
-- =================================================================================

WITH DailyActivities AS (
    -- This CTE combines all raw data from the three sources into one list
    -- before the final grouping.

    -- Part 1: Get daily records for all SERVERS
    SELECT
        s.date AS "Date",
        s.server AS "Worker",
        COALESCE(s.job_title, 'Server') AS "Job Title",
        s.cash_tips AS "Cash Tips",
        s.non_cash_tips AS "Non-Cash Tips",
        s.gratuity AS "Gratuity",
        0 AS "Tips Paid Out",
        s.net_sales AS "Net Sales",
        0 AS "Tips Received",
        NULL AS "Payout Bucket",
        NULL AS "Payout Business Date"
    FROM
        servers s
    WHERE
        date(s.date) <= date('now', 'localtime')

    UNION ALL

    -- Part 2: Get daily records for all BARTENDERS
    SELECT
        b.date AS "Date",
        b.bartender AS "Worker",
        COALESCE(b.job_title, 'Bartender') AS "Job Title",
        b.cash_tips AS "Cash Tips",
        b.credit_tips AS "Non-Cash Tips",
        0 AS "Gratuity",
        0 AS "Tips Paid Out",
        b.net_sales AS "Net Sales",
        0 AS "Tips Received",
        NULL AS "Payout Bucket",
        NULL AS "Payout Business Date"
    FROM
        bartenders b
    WHERE
        date(b.date) <= date('now', 'localtime')

    UNION ALL

    -- Part 3: Tips RECEIVED by workers from committed payouts (ledger)
    -- Join through payout_sessions to show the bucket and business date of the payout session
    SELECT
        COALESCE(s.business_date, date(c.timestamp)) AS "Date",
        c.worker_name AS "Worker",
        REPLACE(c.reason, 'Payout - ', '') AS "Job Title",
        0 AS "Cash Tips",
        0 AS "Non-Cash Tips",
        0 AS "Gratuity",
        0 AS "Tips Paid Out",
        0 AS "Net Sales",
        c.amount AS "Tips Received",
        s.bucket AS "Payout Bucket",
        s.business_date AS "Payout Business Date"
    FROM
        cashbox_ledger c
        LEFT JOIN payout_sessions s ON s.id = c.payout_session_id
    WHERE
        c.reason LIKE 'Payout - %' AND c.amount > 0
        AND date(c.timestamp) <= date('now', 'localtime')

    UNION ALL

    -- Part 4: Tips PAID OUT by submitters (sources) per committed transfer
    -- Use payout_legs for the 'received' leg with party_role = 'Submitter'.
    -- We take the submitter's job_title from the leg (populated when allocating transfers).
    SELECT
        s.business_date AS "Date",
        l.party_name AS "Worker",
        COALESCE(l.job_title, l.destination) AS "Job Title",
        0 AS "Cash Tips",
        0 AS "Non-Cash Tips",
        0 AS "Gratuity",
        l.amount AS "Tips Paid Out",
        0 AS "Net Sales",
        0 AS "Tips Received",
        s.bucket AS "Payout Bucket",
        s.business_date AS "Payout Business Date"
    FROM payout_legs l
    JOIN payout_transfers t ON t.id = l.transfer_id
    JOIN payout_sessions s ON s.id = t.session_id
    WHERE l.leg_kind = 'received' AND l.party_role = 'Submitter'
)

-- Final step: Group all activities by day and worker to consolidate rows
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
    GROUP_CONCAT(DISTINCT "Payout Bucket") AS "Payout Bucket",
    GROUP_CONCAT(DISTINCT "Payout Business Date") AS "Payout Business Date",
    CASE
        WHEN SUM("Net Sales") > 0 THEN
            ROUND((SUM("Cash Tips") + SUM("Non-Cash Tips") + SUM("Gratuity")) * 100.0 / SUM("Net Sales"), 2)
        ELSE 0
    END AS "Tip % of Sales"
FROM
    DailyActivities
GROUP BY
    "Date", "Worker", "Job Title"
ORDER BY
    "Date" DESC, "Worker";
