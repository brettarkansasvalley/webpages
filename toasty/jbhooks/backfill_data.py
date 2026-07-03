import sqlite3
import os
import argparse
import uuid

def backfill_cashbox_ledger(db_path):
    """
    Backfills missing submit_id and payout_session_id in the cashbox_ledger table
    using a simplified matching logic.

    Args:
        db_path (str): The path to the SQLite database file.
    """
    if not os.path.exists(db_path):
        print(f"Error: Database file not found at '{db_path}'")
        return

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        print("Successfully connected to the database.")

        # --- Query 1: Backfill 'payout_session_id' where it is missing ---
        # Find a matching submit_id in the payouts table and copy the payout_session_id.
        print("Attempting to backfill missing 'payout_session_id'...")
        update_payout_session_id_query = """
        UPDATE cashbox_ledger
        SET payout_session_id = (
            SELECT p.payout_session_id
            FROM payouts p
            WHERE p.submit_id = cashbox_ledger.submit_id
            LIMIT 1
        )
        WHERE (payout_session_id IS NULL OR payout_session_id = '')
          AND cashbox_ledger.submit_id IS NOT NULL;
        """
        cursor.execute(update_payout_session_id_query)
        updated_rows_payout_id = cursor.rowcount
        print(f"Updated {updated_rows_payout_id} rows with the missing 'payout_session_id'.")

        # --- Query 2: Backfill 'submit_id' where it is missing ---
        # Find a matching payout_session_id in the payouts table and copy the submit_id.
        print("Attempting to backfill missing 'submit_id'...")
        update_submit_id_query = """
        UPDATE cashbox_ledger
        SET submit_id = (
            SELECT p.submit_id
            FROM payouts p
            WHERE p.payout_session_id = cashbox_ledger.payout_session_id
            LIMIT 1
        )
        WHERE (submit_id IS NULL OR submit_id = '')
          AND cashbox_ledger.payout_session_id IS NOT NULL;
        """
        cursor.execute(update_submit_id_query)
        updated_rows_submit_id = cursor.rowcount
        print(f"Updated {updated_rows_submit_id} rows with the missing 'submit_id'.")

        conn.commit()
        print("Changes have been successfully committed to the database.")

    except sqlite3.Error as e:
        print(f"Database error: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()
            print("Database connection closed.")


def create_payout_sessions_for_unpaid_groups(db_path, write_ledger=False, dry_run=True, limit=None):
    """Create payout sessions for existing unpaid payouts grouped by bucket/date.

    - Groups rows where payouts.payout_session_id IS NULL by (bucket, DATE(timestamp)).
    - Assigns a new payout_session_id per group and updates those payouts rows.
    - Optionally writes matching cashbox_ledger entries per payout row with a Backfill reason.

    Args:
        db_path: path to SQLite database
        write_ledger: if True, also insert cashbox_ledger rows
        dry_run: if True, only print planned actions
        limit: optional limit on number of groups processed
    """
    if not os.path.exists(db_path):
        print(f"Error: Database file not found at '{db_path}'")
        return

    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Identify groups of unpaid payouts by bucket/date
        cursor.execute(
            """
            SELECT bucket, DATE(timestamp) AS biz_date, COUNT(*), COALESCE(SUM(amount), 0.0)
            FROM payouts
            WHERE payout_session_id IS NULL
            GROUP BY bucket, DATE(timestamp)
            ORDER BY biz_date ASC, bucket ASC
            """
        )
        groups = cursor.fetchall()

        if not groups:
            print("No unpaid payouts found. Nothing to backfill.")
            return

        if limit is not None:
            groups = groups[: max(0, int(limit))]

        print(f"Found {len(groups)} unpaid payout group(s). dry_run={dry_run}, write_ledger={write_ledger}")

        # Lazy import to determine drawer per bucket if ledger writes enabled
        if write_ledger:
            from jbhooks.tip_calculator import TipCalculator

        total_groups = 0
        total_rows = 0
        total_amount = 0.0

        for bucket, biz_date, cnt, amt_sum in groups:
            total_groups += 1
            total_amount += float(amt_sum or 0.0)
            print(f"Group bucket={bucket} date={biz_date} rows={cnt} sum=${amt_sum:.2f}")

            # Build session id
            session_id = f"{bucket}-{biz_date}-{uuid.uuid4().hex[:8]}"

            # Fetch row IDs and details for the group
            cursor.execute(
                """
                SELECT id, worker_name, amount, payout_destination, timestamp
                FROM payouts
                WHERE payout_session_id IS NULL AND bucket = ? AND DATE(timestamp) = ?
                ORDER BY id ASC
                """,
                (bucket, biz_date),
            )
            rows = cursor.fetchall()
            total_rows += len(rows)

            if dry_run:
                print(f"  Would set payout_session_id='{session_id}' for {len(rows)} row(s)")
            else:
                cursor.execute(
                    "UPDATE payouts SET payout_session_id = ? WHERE payout_session_id IS NULL AND bucket = ? AND DATE(timestamp) = ?",
                    (session_id, bucket, biz_date),
                )

            if write_ledger:
                drawer = TipCalculator.get_drawer_for_bucket(bucket)
                for pid, worker_name, amount, dest, ts in rows:
                    reason = f"Backfill - {dest}"
                    if dry_run:
                        print(f"    Would ledger: worker={worker_name} amount=${float(amount):.2f} drawer={drawer} reason='{reason}' session={session_id}")
                    else:
                        # Avoid duplicating an identical ledger record for this session
                        cursor.execute(
                            "SELECT COUNT(1) FROM cashbox_ledger WHERE worker_name = ? AND amount = ? AND reason = ? AND cash_drawer = ? AND payout_session_id = ?",
                            (worker_name, float(amount), reason, drawer, session_id),
                        )
                        exists = cursor.fetchone()[0] or 0
                        if exists == 0:
                            cursor.execute(
                                "INSERT INTO cashbox_ledger (worker_name, amount, reason, cash_drawer, payout_session_id) VALUES (?, ?, ?, ?, ?)",
                                (worker_name, float(amount), reason, drawer, session_id),
                            )

            if not dry_run:
                conn.commit()

        print(f"Done. groups={total_groups} rows={total_rows} sum=${total_amount:.2f}")

    except sqlite3.Error as e:
        print(f"Database error: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()
            print("Database connection closed.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Backfill utilities for tip distribution DB")
    parser.add_argument('--db', default='tip_distribution.db', help='Path to SQLite DB file')
    parser.add_argument('--backfill-cashbox-links', action='store_true', help='Backfill payout_session_id/submit_id links between payouts and cashbox_ledger')
    parser.add_argument('--create-sessions', action='store_true', help='Create payout sessions for existing unpaid payouts, grouped by bucket/date')
    parser.add_argument('--write-ledger', action='store_true', help='When creating sessions, also write matching cashbox_ledger rows')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without writing')
    parser.add_argument('--limit', type=int, default=None, help='Limit number of groups to process')

    args = parser.parse_args()

    if not (args.backfill_cashbox_links or args.create_sessions):
        parser.print_help()
        raise SystemExit(1)

    if args.backfill_cashbox_links:
        backfill_cashbox_ledger(args.db)

    if args.create_sessions:
        create_payout_sessions_for_unpaid_groups(
            db_path=args.db,
            write_ledger=args.write_ledger,
            dry_run=args.dry_run,
            limit=args.limit,
        )
