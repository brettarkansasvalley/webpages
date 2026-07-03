#!/usr/bin/env python3
"""
Database operations for the Restaurant Tip Distribution System
"""
#database.py

import sqlite3
import json
from pathlib import Path
from config import DATABASE_FILE


class DatabaseManager:
    def __init__(self):
        self.conn = None
        self.init_database()

    def init_database(self):
        """Initialize the database connection and create tables"""
        # Resolve database path relative to project root (parent of jbhooks)
        db_path = Path(__file__).resolve().parent.parent / DATABASE_FILE if not Path(DATABASE_FILE).is_absolute() else Path(DATABASE_FILE)
        self.conn = sqlite3.connect(str(db_path))
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")

        # Create tables
        cursor.execute('CREATE TABLE IF NOT EXISTS workers (id INTEGER PRIMARY KEY, name TEXT UNIQUE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY, worker_name TEXT, bucket TEXT, 
                bartips REAL, servertips REAL, expotips REAL, runnertips REAL, 
                cashtips REAL, creditcardtip REAL, gratuity REAL, net_sales REAL,
                owed_to_server REAL, owed_to_restaurant REAL, payout_data TEXT, 
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, 
                FOREIGN KEY (worker_name) REFERENCES workers (name) ON DELETE CASCADE
            )
        ''')
        
        # Check if worker_roles table needs to be recreated with new schema
        cursor.execute("PRAGMA table_info(worker_roles)")
        columns = [info[1] for info in cursor.fetchall()]
        
        # Check if table has old schema (composite primary key)
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='worker_roles'")
        table_sql = cursor.fetchone()
        
        if table_sql and 'PRIMARY KEY (worker_name, role)' in table_sql[0]:
            # Need to migrate to new schema
            print("Migrating worker_roles table to new schema...")
            
            # Backup existing data
            cursor.execute('SELECT worker_name, role FROM worker_roles')
            existing_data = cursor.fetchall()
            
            # Drop old table and indexes
            cursor.execute('DROP TABLE IF EXISTS worker_roles')
            cursor.execute('DROP INDEX IF EXISTS idx_unique_worker_name')
            cursor.execute('DROP INDEX IF EXISTS idx_worker_role_key')
        
        # Create worker_roles table with new schema
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS worker_roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_name TEXT,
                role TEXT,
                worker_role_key TEXT UNIQUE,
                FOREIGN KEY (worker_name) REFERENCES workers(name) ON DELETE CASCADE
            )
        ''')
        
        # Restore data if we migrated
        if 'existing_data' in locals() and existing_data:
            print(f"Restoring {len(existing_data)} worker role records...")
            for worker_name, role in existing_data:
                worker_role_key = f"{worker_name}_{role}"
                cursor.execute('INSERT OR IGNORE INTO worker_roles (worker_name, role, worker_role_key) VALUES (?, ?, ?)', 
                             (worker_name, role, worker_role_key))
        
        # Check and add missing columns to transactions table
        cursor.execute("PRAGMA table_info(transactions)")
        columns = [info[1] for info in cursor.fetchall()]
        if 'cashtips' not in columns: cursor.execute('ALTER TABLE transactions ADD COLUMN cashtips REAL DEFAULT 0')
        if 'creditcardtip' not in columns: cursor.execute('ALTER TABLE transactions ADD COLUMN creditcardtip REAL DEFAULT 0')
        if 'gratuity' not in columns: cursor.execute('ALTER TABLE transactions ADD COLUMN gratuity REAL DEFAULT 0')
        if 'net_sales' not in columns: cursor.execute('ALTER TABLE transactions ADD COLUMN net_sales REAL DEFAULT 0')
        if 'owed_to_server' not in columns: cursor.execute('ALTER TABLE transactions ADD COLUMN owed_to_server REAL DEFAULT 0')
        if 'owed_to_restaurant' not in columns: cursor.execute('ALTER TABLE transactions ADD COLUMN owed_to_restaurant REAL DEFAULT 0')

        cursor.execute('CREATE TABLE IF NOT EXISTS worker_assignments (id INTEGER PRIMARY KEY, bucket TEXT, payout_destination TEXT, worker_name TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (worker_name) REFERENCES workers (name) ON DELETE CASCADE)')
        
        cursor.execute('CREATE TABLE IF NOT EXISTS cashbox_ledger (id INTEGER PRIMARY KEY, worker_name TEXT, amount REAL, reason TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, cash_drawer TEXT, submit_id TEXT, payout_session_id TEXT)')
        
        # Check and add missing columns to cashbox_ledger table
        cursor.execute("PRAGMA table_info(cashbox_ledger)")
        columns = [info[1] for info in cursor.fetchall()]
        if 'cash_drawer' not in columns: cursor.execute('ALTER TABLE cashbox_ledger ADD COLUMN cash_drawer TEXT')
        if 'submit_id' not in columns: cursor.execute('ALTER TABLE cashbox_ledger ADD COLUMN submit_id TEXT')
        if 'payout_session_id' not in columns: cursor.execute('ALTER TABLE cashbox_ledger ADD COLUMN payout_session_id TEXT')
        if 'transfer_id' not in columns: cursor.execute('ALTER TABLE cashbox_ledger ADD COLUMN transfer_id INTEGER')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bartenders (
                id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, cash_tips REAL, credit_tips REAL, 
                sum_tips_for_payout REAL, net_sales REAL, tipped_perc_of_net_sales TEXT, 
                hours_worked REAL, job_title TEXT, bartender TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, 
                bar_name TEXT, submit_id TEXT
            )
        ''')
        
        # Check and add missing columns to bartenders table
        cursor.execute("PRAGMA table_info(bartenders)")
        columns = [info[1] for info in cursor.fetchall()]
        if 'bar_name' not in columns: cursor.execute('ALTER TABLE bartenders ADD COLUMN bar_name TEXT')
        if 'submit_id' not in columns: cursor.execute('ALTER TABLE bartenders ADD COLUMN submit_id TEXT')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS servers (
                id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, server TEXT, job_title TEXT, 
                bucket TEXT, cash_tips REAL, non_cash_tips REAL, gratuity REAL, 
                sum_tips_for_payout REAL, net_sales REAL, tipped_perc_of_net_sales TEXT,
                submit_id TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_name TEXT,
                amount REAL,
                bucket TEXT,
                payout_destination TEXT,
                business_date TEXT,
                job_title TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                payout_session_id TEXT,
                submit_id TEXT,
                FOREIGN KEY (worker_name) REFERENCES workers(name) ON DELETE CASCADE
            )
        ''')

        # Check and add missing columns to payouts table
        cursor.execute("PRAGMA table_info(payouts)")
        columns = [info[1] for info in cursor.fetchall()]
        if 'payout_session_id' not in columns:
             cursor.execute('ALTER TABLE payouts ADD COLUMN payout_session_id TEXT')
        if 'submit_id' not in columns:
             cursor.execute('ALTER TABLE payouts ADD COLUMN submit_id TEXT')
        if 'business_date' not in columns:
             cursor.execute('ALTER TABLE payouts ADD COLUMN business_date TEXT')
        if 'claimed_transfer_id' not in columns:
             cursor.execute('ALTER TABLE payouts ADD COLUMN claimed_transfer_id INTEGER')
        if 'job_title' not in columns:
             cursor.execute('ALTER TABLE payouts ADD COLUMN job_title TEXT')

        # Create helpful indexes
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_payouts_bucket ON payouts(bucket)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_payouts_session ON payouts(payout_session_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_payouts_bucket_session ON payouts(bucket, payout_session_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_payouts_date_bucket ON payouts(business_date, bucket)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_worker_assignments_bucket_dest ON worker_assignments(bucket, payout_destination)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_cashbox_ledger_session ON cashbox_ledger(payout_session_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_cashbox_ledger_transfer ON cashbox_ledger(transfer_id)')

        # Double-entry payout journal tables
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payout_sessions (
                id TEXT PRIMARY KEY,
                bucket TEXT,
                business_date TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payout_transfers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                destination TEXT,
                amount REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES payout_sessions(id) ON DELETE CASCADE
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payout_legs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transfer_id INTEGER,
                leg_kind TEXT CHECK(leg_kind IN ("received","given")),
                party_role TEXT,
                party_name TEXT,
                destination TEXT,
                amount REAL NOT NULL,
                reason TEXT,
                cash_drawer TEXT,
                job_title TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (transfer_id) REFERENCES payout_transfers(id) ON DELETE CASCADE
            )
        ''')
        # Add missing job_title column to payout_legs if needed
        cursor.execute("PRAGMA table_info(payout_legs)")
        columns = [info[1] for info in cursor.fetchall()]
        if 'job_title' not in columns:
            cursor.execute('ALTER TABLE payout_legs ADD COLUMN job_title TEXT')

        self.conn.commit()

    def save_server_entry(
        self,
        date_str: str,
        server_name: str,
        bucket: str | None,
        cash_tips: float,
        non_cash_tips: float,
        gratuity: float,
        sum_tips_for_payout: float,
        net_sales: float,
        tipped_perc_of_net_sales: str | None,
        job_title: str | None = None,
        submit_id: str | None = None,
    ) -> None:
        """Upsert a server daily summary row in the `servers` table.

        De-duplicates by (date, server, bucket) so edits overwrite the single daily row.
        """
        cursor = self.conn.cursor()
        # Ensure only one summary row per (date, server, bucket)
        try:
            cursor.execute(
                'DELETE FROM servers WHERE date = ? AND server = ? AND (bucket IS ? OR bucket = ?)',
                (date_str, server_name, bucket, bucket),
            )
        except Exception:
            # If DELETE fails, continue with insert to avoid data loss
            pass
        cursor.execute(
            '''INSERT INTO servers (
                   date, server, job_title, bucket,
                   cash_tips, non_cash_tips, gratuity,
                   sum_tips_for_payout, net_sales, tipped_perc_of_net_sales,
                   submit_id
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                date_str,
                server_name,
                job_title or None,
                bucket or None,
                float(cash_tips or 0.0),
                float(non_cash_tips or 0.0),
                float(gratuity or 0.0),
                float(sum_tips_for_payout or 0.0),
                float(net_sales or 0.0),
                tipped_perc_of_net_sales or "",
                submit_id or None,
            ),
        )
        self.conn.commit()

    # --- Double-entry transfer API ---

    def create_payout_session(self, session_id: str, bucket: str, business_date: str):
        cursor = self.conn.cursor()
        cursor.execute(
            'INSERT OR REPLACE INTO payout_sessions (id, bucket, business_date) VALUES (?, ?, ?)',
            (session_id, bucket, business_date),
        )
        self.conn.commit()

    def _fetch_unpaid_pool_rows(self, bucket: str, business_date: str, destination: str):
        """Fetch unpaid pool rows (sources) for FIFO allocation."""
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT id, worker_name, amount, job_title FROM payouts WHERE bucket = ? AND business_date = ? AND payout_destination = ? AND payout_session_id IS NULL ORDER BY id',
            (bucket, business_date, destination),
        )
        return [
            {"id": int(r[0]), "worker_name": r[1], "amount": float(r[2] or 0.0), "job_title": (r[3] or "")}
            for r in (cursor.fetchall() or [])
        ]

    def _claim_from_source(self, source_id: int, claim_amount: float, session_id: str, transfer_id: int):
        """Claim amount from an unpaid source row. Split row if partially claimed.
        Creates a claimed row with claimed amount and links claimed_transfer_id.
        """
        cursor = self.conn.cursor()
        # Read current amount and fields
        cursor.execute('SELECT worker_name, bucket, payout_destination, business_date, amount, submit_id, job_title FROM payouts WHERE id = ?', (int(source_id),))
        row = cursor.fetchone()
        if not row:
            return
        wname, bucket, dest, bdate, cur_amt, submit_id, job_title = row
        cur_amt = float(cur_amt or 0.0)
        claim_amount = min(float(claim_amount or 0.0), cur_amt)
        remaining = cur_amt - claim_amount
        # Insert claimed row
        cursor.execute(
            'INSERT INTO payouts (worker_name, amount, bucket, payout_destination, business_date, payout_session_id, submit_id, claimed_transfer_id, job_title) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (wname, claim_amount, bucket, dest, bdate, session_id, submit_id, transfer_id, job_title),
        )
        # Update or delete source row depending on remainder
        if remaining > 1e-9:
            cursor.execute('UPDATE payouts SET amount = ? WHERE id = ?', (remaining, int(source_id)))
        else:
            cursor.execute('DELETE FROM payouts WHERE id = ?', (int(source_id),))
        self.conn.commit()

    def allocate_and_commit_transfers(self, bucket: str, business_date: str, distributions: dict, session_id: str, reason_prefix: str = "Payout") -> float:
        """Allocate unpaid pools (sources) into balanced transfers based on per-worker destination amounts.

        Returns the total committed amount.
        """
        from tip_calculator import TipCalculator  # lazy import
        cash_drawer = TipCalculator.get_drawer_for_bucket(bucket)
        cursor = self.conn.cursor()
        session_total = 0.0

        # Build per-destination requirements from distributions
        # distributions: { worker_name: { dest: amount } }
        dest_requirements = {"Bartender": [], "Busser": [], "Expo": [], "Runner": []}
        dest_primary_worker: dict[str, str] = {}
        for worker, dmap in (distributions or {}).items():
            for dest, amt in (dmap or {}).items():
                amt = float(amt or 0.0)
                if amt <= 0:
                    continue
                if dest not in dest_requirements:
                    dest_requirements[dest] = []
                dest_requirements[dest].append({"worker": worker, "remaining": amt})
                # First encountered worker per destination becomes the primary for penny sweep
                dest_primary_worker.setdefault(dest, worker)

        for dest, needs in dest_requirements.items():
            # Load all sources for this destination (even if there are no positive needs)
            sources = self._fetch_unpaid_pool_rows(bucket, business_date, dest)
            created_any_for_dest = False
            if not needs:
                # If there are unpaid pool rows but their total is zero, create zero-amount marker transfers
                # so the commit is tracked and can be deleted later.
                try:
                    if sources and (sum(max(0.0, s["amount"]) for s in sources) <= 1e-9):
                        for src in sources:
                            submitter = src.get("worker_name") or ""
                            worker = submitter  # self-link if no specific worker needs
                            reason = f"{reason_prefix} - {dest} (Zero Commit)"
                            # Create zero-amount transfer
                            cursor.execute(
                                'INSERT INTO payout_transfers (session_id, destination, amount) VALUES (?, ?, ?)',
                                (session_id, dest, 0.0),
                            )
                            transfer_id = cursor.lastrowid
                            # Legs (both zero) to link parties for deletion later
                            cursor.execute(
                                'INSERT INTO payout_legs (transfer_id, leg_kind, party_role, party_name, destination, amount, reason, cash_drawer, job_title) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                                (transfer_id, 'received', 'Submitter', submitter, dest, 0.0, reason, cash_drawer, (src.get('job_title') or None)),
                            )
                            cursor.execute(
                                'INSERT INTO payout_legs (transfer_id, leg_kind, party_role, party_name, destination, amount, reason, cash_drawer, job_title) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                                (transfer_id, 'given', 'Worker', worker, dest, 0.0, reason, cash_drawer, None),
                            )
                            # Optional ledger linkage for symmetry
                            cursor.execute(
                                'INSERT INTO cashbox_ledger (worker_name, amount, reason, cash_drawer, payout_session_id, transfer_id) VALUES (?, ?, ?, ?, ?, ?)',
                                (worker, 0.0, reason, cash_drawer, session_id, transfer_id),
                            )
                            # Claim zero from source to link claimed row to transfer/session and remove unpaid source
                            self._claim_from_source(src["id"], 0.0, session_id, transfer_id)
                        self.conn.commit()
                except Exception:
                    # Non-fatal: leave as unpaid if marker creation fails
                    pass
                # Move on to next destination
                continue
            # Work with a dynamic list of remaining amounts
            while True:
                # Stop if no remaining pool
                total_pool = sum(max(0.0, s["amount"]) for s in sources)
                if total_pool <= 1e-9:
                    break
                # Find next worker with remaining need
                need_idx = next((i for i, n in enumerate(needs) if n["remaining"] > 1e-9), None)
                if need_idx is None:
                    break
                need = needs[need_idx]
                to_allocate = need["remaining"]
                if to_allocate <= 1e-9:
                    continue
                reason = f"{reason_prefix} - {dest}"
                # Allocate proportionally from all sources based on their remaining
                allocations = []  # list of dicts: {idx, src_id, submitter, take}
                for idx, src in enumerate(sources):
                    src_rem = max(0.0, src["amount"])
                    if src_rem <= 1e-9:
                        continue
                    proportion = src_rem / total_pool
                    ideal_take = min(src_rem, to_allocate * proportion)
                    if ideal_take <= 1e-9:
                        continue
                    allocations.append({
                        "idx": idx,
                        "src_id": src["id"],
                        "submitter": src["worker_name"],
                        "ideal": ideal_take,
                    })
                if not allocations:
                    break
                # Round each allocation to cents and adjust remainder to sum to nearest cent of to_allocate
                rounded_allocs = []
                rounded_sum = 0.0
                for a in allocations:
                    r = round(a["ideal"] + 1e-9, 2)
                    if r < 0.01:
                        r = 0.0
                    rounded_allocs.append({**a, "take": r})
                    rounded_sum += r
                target_sum = round(to_allocate + 1e-9, 2)
                remainder = round(target_sum - rounded_sum, 2)
                if abs(remainder) >= 0.01:
                    # Adjust the largest ideal_take slice if possible
                    rounded_allocs.sort(key=lambda x: x["ideal"], reverse=True)
                    for ra in rounded_allocs:
                        idx = ra["idx"]
                        src = sources[idx]
                        capacity = round(max(0.0, src["amount"]) - ra["take"] + 1e-9, 2)
                        if remainder > 0 and capacity >= 0.01:
                            bump = min(remainder, capacity)
                            ra["take"] = round(ra["take"] + bump, 2)
                            remainder = round(remainder - bump, 2)
                            if abs(remainder) < 0.01:
                                break
                        elif remainder < 0 and ra["take"] >= 0.01:
                            drop = min(abs(remainder), ra["take"])  # reduce this slice
                            ra["take"] = round(ra["take"] - drop, 2)
                            remainder = round(remainder + drop, 2)
                            if abs(remainder) < 0.01:
                                break
                    # Restore original order
                    rounded_allocs.sort(key=lambda x: x["idx"]) 
                # Apply non-zero rounded allocations
                for ra in rounded_allocs:
                    take = ra["take"]
                    if take < 0.01:
                        continue
                    # Create transfer for this rounded slice
                    cursor.execute(
                        'INSERT INTO payout_transfers (session_id, destination, amount) VALUES (?, ?, ?)',
                        (session_id, dest, take),
                    )
                    transfer_id = cursor.lastrowid
                    created_any_for_dest = True
                    # Legs
                    cursor.execute(
                        'INSERT INTO payout_legs (transfer_id, leg_kind, party_role, party_name, destination, amount, reason, cash_drawer, job_title) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (transfer_id, 'received', 'Submitter', ra["submitter"], dest, take, reason, cash_drawer, (sources[ra["idx"]].get("job_title") or None)),
                    )
                    cursor.execute(
                        'INSERT INTO payout_legs (transfer_id, leg_kind, party_role, party_name, destination, amount, reason, cash_drawer, job_title) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (transfer_id, 'given', 'Worker', need["worker"], dest, take, reason, cash_drawer, None),
                    )
                    # Cashbox entry for given leg
                    cursor.execute(
                        'INSERT INTO cashbox_ledger (worker_name, amount, reason, cash_drawer, payout_session_id, transfer_id) VALUES (?, ?, ?, ?, ?, ?)',
                        (need["worker"], take, reason, cash_drawer, session_id, transfer_id),
                    )
                    # Claim from source
                    self._claim_from_source(ra["src_id"], take, session_id, transfer_id)
                    # Update trackers
                    sources[ra["idx"]]["amount"] = round(max(0.0, sources[ra["idx"]]["amount"] - take), 2)
                    to_allocate = round(max(0.0, to_allocate - take), 2)
                    session_total += take
                    if to_allocate <= 1e-9:
                        break
                # Save back remaining
                needs[need_idx]["remaining"] = to_allocate

            # Penny sweep: consume any remaining unpaid cents for this destination
            sources = self._fetch_unpaid_pool_rows(bucket, business_date, dest)
            residual = round(sum(max(0.0, s["amount"]) for s in sources), 2)
            if residual >= 0.01:
                primary_worker = dest_primary_worker.get(dest) or (needs[0]["worker"] if needs else None)
                if primary_worker:
                    reason = f"{reason_prefix} - {dest} (Penny Sweep)"
                    # Iterate cent-by-cent to fully zero out
                    cents = int(round(residual * 100))
                    si = 0
                    for _ in range(cents):
                        # Refresh current source pointer if needed
                        while si < len(sources) and round(sources[si]["amount"], 2) < 0.01:
                            si += 1
                        if si >= len(sources):
                            # Re-fetch in case prior claims changed ordering
                            sources = self._fetch_unpaid_pool_rows(bucket, business_date, dest)
                            si = 0
                            while si < len(sources) and round(sources[si]["amount"], 2) < 0.01:
                                si += 1
                            if si >= len(sources):
                                break
                        src = sources[si]
                        take = 0.01
                        # Create a 1-cent transfer
                        cursor.execute(
                            'INSERT INTO payout_transfers (session_id, destination, amount) VALUES (?, ?, ?)',
                            (session_id, dest, take),
                        )
                        transfer_id = cursor.lastrowid
                        created_any_for_dest = True
                        # Legs
                        cursor.execute(
                            'INSERT INTO payout_legs (transfer_id, leg_kind, party_role, party_name, destination, amount, reason, cash_drawer, job_title) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                            (transfer_id, 'received', 'Submitter', src["worker_name"], dest, take, reason, cash_drawer, (src.get("job_title") or None)),
                        )
                        cursor.execute(
                            'INSERT INTO payout_legs (transfer_id, leg_kind, party_role, party_name, destination, amount, reason, cash_drawer, job_title) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                            (transfer_id, 'given', 'Worker', primary_worker, dest, take, reason, cash_drawer, None),
                        )
                        cursor.execute(
                            'INSERT INTO cashbox_ledger (worker_name, amount, reason, cash_drawer, payout_session_id, transfer_id) VALUES (?, ?, ?, ?, ?, ?)',
                            (primary_worker, take, reason, cash_drawer, session_id, transfer_id),
                        )
                        self._claim_from_source(src["id"], take, session_id, transfer_id)
                        # Update local tracker
                        src["amount"] = round(max(0.0, src["amount"] - take), 2)
                        session_total = round(session_total + take, 2)
        self.conn.commit()
        return session_total

    def get_committed_transfers(self, bucket: str, business_date: str) -> list[dict]:
        """Return committed transfers for a bucket/date with balanced columns.

        Each row: { id, timestamp, payout_session_id, worker_name, destination, amount_received, amount_given }
        """
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT t.id, t.created_at, t.session_id, t.destination, t.amount, "
            "  COALESCE(SUM(CASE WHEN l.leg_kind = 'received' THEN l.amount END), 0.0) AS amt_received, "
            "  COALESCE(SUM(CASE WHEN l.leg_kind = 'given' THEN l.amount END), 0.0) AS amt_given, "
            "  MAX(CASE WHEN l.leg_kind = 'given' THEN l.party_name END) AS worker_name, "
            "  MAX(CASE WHEN l.leg_kind = 'received' THEN l.party_name END) AS submitter_name "
            "FROM payout_transfers t "
            "JOIN payout_sessions s ON s.id = t.session_id "
            "LEFT JOIN payout_legs l ON l.transfer_id = t.id "
            "WHERE s.bucket = ? AND s.business_date = ? "
            "GROUP BY t.id, t.created_at, t.session_id, t.destination, t.amount "
            "ORDER BY datetime(t.created_at) DESC, t.session_id, worker_name, t.destination",
            (bucket, business_date),
        )
        rows = cursor.fetchall() or []
        out = []
        for rid, ts, sess, dest, t_amount, a_recv, a_give, wname, submitter in rows:
            try:
                t_amount = float(t_amount or 0.0)
            except Exception:
                t_amount = 0.0
            # Fallback: if legs sum to zero but transfer has amount, use t_amount
            if (a_recv or 0.0) == 0.0 and (a_give or 0.0) == 0.0 and t_amount > 0:
                a_recv = t_amount
                a_give = t_amount
            out.append({
                "id": int(rid),
                "timestamp": ts,
                "payout_session_id": sess,
                "worker_name": wname or "",
                "destination": dest,
                "transfer_amount": t_amount,
                "amount_received": float(a_recv or 0.0),
                "amount_given": float(a_give or 0.0),
                "submitter_name": submitter or "",
            })
        return out

    def get_committed_sums_for_submitter(self, submitter_name: str, bucket: str, business_date: str) -> dict:
        """Return committed sums for a specific submitter (server/bartender) by destination, using transfer legs.

        We sum legs where leg_kind = 'received' and party_name = submitter_name, for transfers in sessions matching bucket and business_date.
        Returns dict with keys: 'Bartender','Busser','Expo','Runner'.
        """
        out = {"Bartender": 0.0, "Busser": 0.0, "Expo": 0.0, "Runner": 0.0}
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT l.destination, COALESCE(SUM(l.amount),0.0) "
            "FROM payout_legs l "
            "JOIN payout_transfers t ON t.id = l.transfer_id "
            "JOIN payout_sessions s ON s.id = t.session_id "
            "WHERE s.bucket = ? AND s.business_date = ? AND l.leg_kind = 'received' AND l.party_name = ? "
            "GROUP BY l.destination",
            (bucket, business_date, submitter_name),
        )
        for dest, total in cursor.fetchall() or []:
            if dest in out:
                out[dest] = float(total or 0.0)
        return out

    def delete_committed_transfer(self, transfer_id: int) -> dict:
        """Delete a committed transfer and matching cashbox ledger rows.

        Returns: { 'transfers_deleted': int, 'legs_deleted': int, 'ledger_deleted': int }
        """
        cursor = self.conn.cursor()
        # Reverse claimed payouts for this transfer back to unpaid pool
        cursor.execute('SELECT id, worker_name, bucket, payout_destination, business_date, amount, submit_id FROM payouts WHERE claimed_transfer_id = ?', (int(transfer_id),))
        claimed_rows = cursor.fetchall() or []
        restored = 0
        for pid, wname, bucket, dest, bdate, amt, submit_id in claimed_rows:
            # Delete the claimed row
            cursor.execute('DELETE FROM payouts WHERE id = ?', (int(pid),))
            # Recreate as unpaid source
            cursor.execute(
                'INSERT INTO payouts (worker_name, amount, bucket, payout_destination, business_date, submit_id) VALUES (?, ?, ?, ?, ?, ?)',
                (wname, float(amt or 0.0), bucket, dest, bdate, submit_id),
            )
            restored += 1
        # Delete cashbox entries first
        cursor.execute('DELETE FROM cashbox_ledger WHERE transfer_id = ?', (int(transfer_id),))
        ledger_deleted = cursor.rowcount or 0
        # Delete legs then transfer
        cursor.execute('DELETE FROM payout_legs WHERE transfer_id = ?', (int(transfer_id),))
        legs_deleted = cursor.rowcount or 0
        cursor.execute('DELETE FROM payout_transfers WHERE id = ?', (int(transfer_id),))
        transfers_deleted = cursor.rowcount or 0
        self.conn.commit()
        return {"transfers_deleted": transfers_deleted, "legs_deleted": legs_deleted, "ledger_deleted": ledger_deleted, "sources_restored": restored}

    def save_bartender_entry(self, date_str, bartender, bar_name, cash_tips, credit_tips, sum_tips_for_payout, net_sales, tipped_perc_of_net_sales, job_title=None, hours_worked=None, submit_id=None):
        """Insert a bartender ledger entry.

        Parameters:
        - date_str: business date (YYYY-MM-DD)
        - bartender: worker name
        - bar_name: display name of bar (e.g., 'AM', 'West Wing', 'Sunset')
        - cash_tips, credit_tips, sum_tips_for_payout, net_sales: floats
        - tipped_perc_of_net_sales: formatted string like 'Gross Tip %: 12.34%'
        - job_title: optional
        - hours_worked: optional float
        - submit_id: optional identifier
        """
        cursor = self.conn.cursor()
        # De-duplicate: ensure only one summary row per (date, bartender, bar_name)
        try:
            cursor.execute(
                'DELETE FROM bartenders WHERE date = ? AND bartender = ? AND bar_name = ?',
                (date_str, bartender, bar_name),
            )
        except Exception:
            pass
        cursor.execute(
            '''INSERT INTO bartenders (date, cash_tips, credit_tips, sum_tips_for_payout, net_sales, tipped_perc_of_net_sales, hours_worked, job_title, bartender, bar_name, submit_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                date_str,
                float(cash_tips or 0),
                float(credit_tips or 0),
                float(sum_tips_for_payout or 0),
                float(net_sales or 0),
                tipped_perc_of_net_sales or "",
                hours_worked if hours_worked is not None else None,
                job_title or None,
                bartender,
                bar_name,
                submit_id or None,
            ),
        )
        self.conn.commit()

    def delete_bartender_entry(self, date_str: str, bartender: str, bar_name: str) -> int:
        """Delete bartender ledger entry rows for a given (date, bartender, bar_name).

        Returns number of rows deleted.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            'DELETE FROM bartenders WHERE date = ? AND bartender = ? AND bar_name = ?',
            (date_str, bartender, bar_name),
        )
        self.conn.commit()
        return cursor.rowcount or 0

    def load_workers(self):
        """Load all workers from database"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT name FROM workers ORDER BY name')
        return [row[0] for row in cursor.fetchall()]

    def add_worker(self, name):
        """Add a new worker to the database"""
        if not name.strip(): 
            return False
        try:
            cursor = self.conn.cursor()
            cursor.execute('INSERT INTO workers (name) VALUES (?)', (name.strip(),))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError: 
            return False

    def save_transaction(self, worker_name, bucket, tips, payouts):
        """Save a transaction to the database"""
        cursor = self.conn.cursor()
        payout_json = json.dumps(payouts) if payouts else None
        
        all_tips = {
            'worker_name': worker_name, 'bucket': bucket,
            'bartips': tips.get('bartips', 0), 'servertips': tips.get('servertips', 0),
            'expotips': tips.get('expotips', 0), 'runnertips': tips.get('runnertips', 0),
            'cashtips': tips.get('cashtips', 0), 'creditcardtip': tips.get('creditcardtip', 0),
            'gratuity': tips.get('gratuity', 0), 'net_sales': tips.get('netsales', 0),
            'owed_to_server': tips.get('owed_to_server', 0), 'owed_to_restaurant': tips.get('owed_to_restaurant', 0),
            'payout_data': payout_json
        }

        cursor.execute("SELECT id FROM transactions WHERE worker_name = ? AND bucket = ?", (worker_name, bucket))
        existing_id = cursor.fetchone()

        if existing_id:
            update_str = ", ".join([f"{key} = :{key}" for key in all_tips if key not in ['worker_name', 'bucket']])
            query = f"UPDATE transactions SET {update_str} WHERE id = {existing_id[0]}"
            cursor.execute(query, all_tips)
        else:
            cols = ", ".join(all_tips.keys())
            placeholders = ", ".join([f":{key}" for key in all_tips.keys()])
            query = f"INSERT INTO transactions ({cols}) VALUES ({placeholders})"
            cursor.execute(query, all_tips)

        self.conn.commit()

    def load_assignments_from_database(self):
        """Load worker assignments from database"""
        worker_assignments = {}
        cursor = self.conn.cursor()
        cursor.execute('SELECT bucket, payout_destination, worker_name FROM worker_assignments')
        for bucket, dest, worker in cursor.fetchall():
            if bucket not in worker_assignments:
                worker_assignments[bucket] = {}
            if dest not in worker_assignments[bucket]:
                worker_assignments[bucket][dest] = []
            worker_assignments[bucket][dest].append(worker)
        return worker_assignments

    def fetch_assignments_for_bucket(self, bucket):
        """Return assignments for a single bucket as {destination: [workers]}"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT payout_destination, worker_name FROM worker_assignments WHERE bucket = ?', (bucket,))
        result = {}
        for dest, worker in cursor.fetchall():
            result.setdefault(dest, []).append(worker)
        return result

    def set_worker_assignments(self, bucket, destination, workers):
        """Replace assignments for a bucket/destination with provided workers"""
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM worker_assignments WHERE bucket = ? AND payout_destination = ?', (bucket, destination))
        for w in (workers or []):
            cursor.execute(
                'INSERT INTO worker_assignments (bucket, payout_destination, worker_name) VALUES (?, ?, ?)',
                (bucket, destination, w),
            )
        self.conn.commit()

    def insert_payout_records(self, bucket, distributions, payout_session_id=None, submit_id=None, business_date=None):
        """Insert payouts for each worker/destination based on distributions dict.

        distributions format: { worker_name: { destination: amount, ... }, ... }

        The inserted rows will include payout_session_id when provided, so they are
        immediately considered claimed as part of that session.
        """
        cursor = self.conn.cursor()
        for worker, dest_map in (distributions or {}).items():
            for destination, amount in (dest_map or {}).items():
                if amount and amount != 0:
                    cursor.execute(
                        'INSERT INTO payouts (worker_name, amount, bucket, payout_destination, business_date, payout_session_id, submit_id) VALUES (?, ?, ?, ?, ?, ?, ?)',
                        (worker, float(amount), bucket, destination, business_date, payout_session_id, submit_id),
                    )
        self.conn.commit()

    def insert_cashbox_ledger_entries(self, bucket, distributions, payout_session_id, submit_id=None, reason_prefix="Payout"):
        """Write cashbox ledger entries for a payout session based on distributions.

        distributions format: { worker_name: { destination: amount, ... }, ... }
        """
        # Lazy import to avoid any circular import at module load time
        from tip_calculator import TipCalculator

        cash_drawer = TipCalculator.get_drawer_for_bucket(bucket)
        cursor = self.conn.cursor()
        for worker, dest_map in (distributions or {}).items():
            for destination, amount in (dest_map or {}).items():
                if amount and amount != 0:
                    reason = f"{reason_prefix} - {destination}"
                    cursor.execute(
                        'INSERT INTO cashbox_ledger (worker_name, amount, reason, cash_drawer, payout_session_id, submit_id) VALUES (?, ?, ?, ?, ?, ?)',
                        (worker, float(amount), reason, cash_drawer, payout_session_id, submit_id),
                    )
        self.conn.commit()

    def get_unpaid_payout_sums(self, bucket, business_date=None):
        """Return {destination: total_amount} for unpaid payouts in a bucket, optionally filtered by business_date (YYYY-MM-DD)."""
        cursor = self.conn.cursor()
        if business_date:
            cursor.execute(
                'SELECT payout_destination, SUM(amount) FROM payouts WHERE bucket = ? AND business_date = ? AND payout_session_id IS NULL GROUP BY payout_destination',
                (bucket, business_date),
            )
        else:
            cursor.execute(
                'SELECT payout_destination, SUM(amount) FROM payouts WHERE bucket = ? AND payout_session_id IS NULL GROUP BY payout_destination',
                (bucket,),
            )
        return {row[0]: (row[1] or 0.0) for row in cursor.fetchall()}

    def mark_payouts_claimed(self, bucket, payout_session_id):
        """Mark all unpaid payouts for a bucket as claimed by setting payout_session_id."""
        cursor = self.conn.cursor()
        cursor.execute(
            'UPDATE payouts SET payout_session_id = ? WHERE bucket = ? AND payout_session_id IS NULL',
            (payout_session_id, bucket),
        )
        self.conn.commit()

    def record_bartender_payouts(self, bartender_name, bucket, bartips=0.0, servertips=0.0, expotips=0.0, runnertips=0.0, submit_id=None, business_date=None, job_title: str | None = None):
        """Record raw payout pools from a bartender entry into payouts table.

        We store one row per destination with the amount contributed by this bartender.
        Destinations: 'Bartender', 'Busser', 'Expo', 'Runner'
        """
        cursor = self.conn.cursor()
        entries = [
            (bartender_name, float(bartips or 0),     bucket, 'Bartender', submit_id, business_date, job_title),
            (bartender_name, float(servertips or 0),  bucket, 'Busser',    submit_id, business_date, job_title),
            (bartender_name, float(expotips or 0),    bucket, 'Expo',      submit_id, business_date, job_title),
            (bartender_name, float(runnertips or 0),  bucket, 'Runner',    submit_id, business_date, job_title),
        ]
        for worker_name, amount, bkt, dest, sid, bdate, jt in entries:
            # Insert even when amount == 0.0 so zeros are visible in Payouts breakdown and sums
            cursor.execute(
                'INSERT INTO payouts (worker_name, amount, bucket, payout_destination, business_date, submit_id, job_title) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (worker_name, float(amount or 0.0), bkt, dest, bdate, sid, jt),
            )
        self.conn.commit()

    def record_server_payouts(self, server_name, bucket, business_date, bartips=0.0, servertips=0.0, expotips=0.0, runnertips=0.0, submit_id=None, job_title: str | None = None):
        """Record raw payout pools from a server entry into payouts table for a specific business date.

        Destinations: 'Bartender', 'Busser', 'Expo', 'Runner'
        """
        cursor = self.conn.cursor()
        entries = [
            (server_name, float(bartips or 0), bucket, 'Bartender', business_date, submit_id, job_title),
            (server_name, float(servertips or 0), bucket, 'Busser', business_date, submit_id, job_title),
            (server_name, float(expotips or 0), bucket, 'Expo', business_date, submit_id, job_title),
            (server_name, float(runnertips or 0), bucket, 'Runner', business_date, submit_id, job_title),
        ]
        for worker_name, amount, bkt, dest, bdate, sid, jt in entries:
            # Insert even when amount == 0.0 so zeros are visible in Payouts breakdown and sums
            cursor.execute(
                'INSERT INTO payouts (worker_name, amount, bucket, payout_destination, business_date, submit_id, job_title) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (worker_name, float(amount or 0.0), bkt, dest, bdate, sid, jt),
            )
        self.conn.commit()

    def get_unpaid_pushed_sums_for_server(self, worker_name: str, bucket: str, business_date: str) -> dict:
        """Return unpaid pushed sums for a specific server/date/bucket as
        { 'Bartender': x, 'Busser': y, 'Expo': z, 'Runner': w }.

        Filters rows in payouts by worker_name, bucket, business_date and payout_session_id IS NULL.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT payout_destination, SUM(amount) FROM payouts WHERE worker_name = ? AND bucket = ? AND business_date = ? AND payout_session_id IS NULL GROUP BY payout_destination',
            (worker_name, bucket, business_date),
        )
        rows = cursor.fetchall()
        out = {"Bartender": 0.0, "Busser": 0.0, "Expo": 0.0, "Runner": 0.0}
        for dest, total in rows:
            if dest in out:
                out[dest] = float(total or 0.0)
        return out

    def get_committed_sums_for_server(self, worker_name: str, bucket: str, business_date: str) -> dict:
        """Return committed (claimed) payout sums for a specific server/date/bucket as
        { 'Bartender': x, 'Busser': y, 'Expo': z, 'Runner': w }.

        Filters rows in payouts by worker_name, bucket, business_date and payout_session_id IS NOT NULL.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT payout_destination, SUM(amount) FROM payouts WHERE worker_name = ? AND bucket = ? AND business_date = ? AND payout_session_id IS NOT NULL GROUP BY payout_destination',
            (worker_name, bucket, business_date),
        )
        rows = cursor.fetchall()
        out = {"Bartender": 0.0, "Busser": 0.0, "Expo": 0.0, "Runner": 0.0}
        for dest, total in rows:
            if dest in out:
                out[dest] = float(total or 0.0)
        return out

    def get_committed_payouts(self, bucket: str, business_date: str) -> list[dict]:
        """Return committed payouts (with payout_session_id) for a bucket and date.

        Each row: {
          'timestamp': str,
          'payout_session_id': str,
          'worker_name': str,
          'destination': str,
          'amount': float,
        }
        """
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT id, timestamp, payout_session_id, worker_name, payout_destination, amount '
            'FROM payouts WHERE bucket = ? AND business_date = ? AND payout_session_id IS NOT NULL '
            'ORDER BY datetime(timestamp) DESC, payout_session_id, worker_name, payout_destination',
            (bucket, business_date),
        )
        rows = cursor.fetchall() or []
        return [
            {
                "id": int(r[0]),
                "timestamp": r[1],
                "payout_session_id": r[2],
                "worker_name": r[3],
                "destination": r[4],
                "amount": float(r[5] or 0.0),
            }
            for r in rows
        ]

    def delete_committed_payout(self, payout_id: int) -> dict:
        """Delete a committed payout row by id and cascade-delete matching cashbox_ledger entries.

        Returns a dict with counts: { 'payouts_deleted': int, 'ledger_deleted': int }
        """
        cursor = self.conn.cursor()
        # Fetch details for cascade into cashbox ledger
        cursor.execute(
            'SELECT payout_session_id, worker_name, payout_destination FROM payouts WHERE id = ? AND payout_session_id IS NOT NULL',
            (int(payout_id),),
        )
        row = cursor.fetchone()
        if not row:
            return {"payouts_deleted": 0, "ledger_deleted": 0}
        session_id, worker_name, destination = row
        # Delete the payout row
        cursor.execute('DELETE FROM payouts WHERE id = ?', (int(payout_id),))
        payouts_deleted = cursor.rowcount or 0
        # Delete matching ledger entries
        reason = f"Payout - {destination}"
        cursor.execute(
            'DELETE FROM cashbox_ledger WHERE payout_session_id = ? AND worker_name = ? AND reason = ?',
            (session_id, worker_name, reason),
        )
        ledger_deleted = cursor.rowcount or 0
        self.conn.commit()
        return {"payouts_deleted": payouts_deleted, "ledger_deleted": ledger_deleted}

    def delete_unpaid_server_payouts(self, worker_name: str, bucket: str, business_date: str) -> int:
        """Delete unpaid payout rows for a server on a given date and bucket.

        Returns the number of rows deleted.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            'DELETE FROM payouts WHERE worker_name = ? AND bucket = ? AND business_date = ? AND payout_session_id IS NULL',
            (worker_name, bucket, business_date),
        )
        self.conn.commit()
        return cursor.rowcount or 0

    def get_unpaid_pushed_breakdown(self, bucket: str, business_date: str) -> list[dict]:
        """Return a list of rows with unpaid pushed sums grouped by server and destination.

        Each row: { 'worker_name': str, 'destination': str, 'amount': float }
        Filters: bucket, business_date, payout_session_id IS NULL
        """
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT worker_name, payout_destination, SUM(amount) as total '
            'FROM payouts '
            'WHERE bucket = ? AND business_date = ? AND payout_session_id IS NULL '
            'GROUP BY worker_name, payout_destination '
            'ORDER BY worker_name, payout_destination',
            (bucket, business_date),
        )
        rows = cursor.fetchall() or []
        out = []
        for w, d, a in rows:
            out.append({
                "worker_name": w,
                "destination": d,
                "amount": float(a or 0.0),
            })
        return out

    def recalculate_all_data_from_source(self, buckets):
        """Recalculate all worker tips data from database"""
        worker_tips = {}
        for bucket in buckets:
            buckets[bucket]["tips"] = {k: 0.0 for k in buckets[bucket]["tips"]}
        
        cursor = self.conn.cursor()
        cursor.execute('SELECT worker_name, bucket, bartips, servertips, expotips, runnertips, cashtips, creditcardtip, gratuity, net_sales, owed_to_server, owed_to_restaurant FROM transactions')
        
        for row in cursor.fetchall():
            worker, bucket, bt, st, et, rt, ct, cct, g, ns, ots, otr = row
            
            if worker not in worker_tips:
                worker_tips[worker] = {}
            if bucket not in worker_tips[worker]:
                worker_tips[worker][bucket] = {}

            data = {
                'bartips': bt, 'servertips': st, 'expotips': et, 'runnertips': rt,
                'cashtips': ct, 'creditcardtip': cct, 'gratuity': g,
                'netsales': ns, 'owed_to_server': ots, 'owed_to_restaurant': otr
            }
            worker_tips[worker][bucket] = data

        return worker_tips

    def get_worker_roles(self, worker_name):
        """Get roles for a specific worker"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT role FROM worker_roles WHERE worker_name = ?', (worker_name,))
        return [row[0] for row in cursor.fetchall()]

    def update_worker_roles(self, worker_name, roles):
        """Update roles for a worker"""
        cursor = self.conn.cursor()
        try:
            # Start transaction
            cursor.execute('BEGIN TRANSACTION')
            
            # Delete existing roles for this worker
            cursor.execute('DELETE FROM worker_roles WHERE worker_name = ?', (worker_name,))
            
            # Insert new roles with concatenated key
            for role in roles:
                worker_role_key = f"{worker_name}_{role}"
                cursor.execute('INSERT OR REPLACE INTO worker_roles (worker_name, role, worker_role_key) VALUES (?, ?, ?)', (worker_name, role, worker_role_key))
            
            # Commit transaction
            self.conn.commit()
        except Exception as e:
            # Rollback on error
            self.conn.rollback()
            raise e

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
