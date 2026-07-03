#!/usr/bin/env python3
"""
Tip calculation business logic for the Restaurant Tip Distribution System
"""
#tip_calculator.py
from config import BUCKETS


class TipCalculator:
    def __init__(self):
        pass

    @staticmethod
    def calculate_bucket_totals(bucket_id, worker_tips, worker_assignments):
        """Calculate totals for a specific bucket"""
        bucket_data = BUCKETS[bucket_id]
        
        # Reset bucket totals
        for tip_type in bucket_data["tips"]:
            bucket_data["tips"][tip_type] = 0.0

        # Calculate totals from worker tips
        for worker_name, worker_buckets in worker_tips.items():
            if bucket_id in worker_buckets:
                worker_data = worker_buckets[bucket_id]
                bucket_data["tips"]["bartips"] += worker_data.get('bartips', 0)
                bucket_data["tips"]["servertips"] += worker_data.get('servertips', 0)
                bucket_data["tips"]["expotips"] += worker_data.get('expotips', 0)
                bucket_data["tips"]["runnertips"] += worker_data.get('runnertips', 0)

        return bucket_data

    @staticmethod
    def calculate_gross_tip_percentage(cash_tips, credit_tips, gratuity, net_sales):
        """Calculate gross tip percentage"""
        if net_sales > 0:
            total_tips = cash_tips + credit_tips + gratuity
            percentage = (total_tips / net_sales) * 100
            return f"Gross Tip %: {percentage:.2f}%"
        return "Gross Tip %: N/A"

    @staticmethod
    def calculate_owed_amounts(cash_tips, credit_tips, gratuity, payout_tips):
        """Calculate amounts owed to server and restaurant"""
        total_received = cash_tips + credit_tips + gratuity
        owed_to_server = max(0, payout_tips - total_received)
        owed_to_restaurant = max(0, total_received - payout_tips)
        return owed_to_server, owed_to_restaurant

    @staticmethod
    def get_drawer_for_bucket(bucket):
        """Get the cash drawer name for a bucket"""
        drawer_map = {
            "am_bar": "AM Bar",
            "westwing": "West Wing Bar", 
            "sunset": "Sunset Bar",
            "eastwing": "Office"
        }
        return drawer_map.get(bucket, "Office")

    @staticmethod
    def calculate_payout_distribution(bucket_id, worker_assignments, tip_amounts, hours_by_worker=None):
        """Calculate how tips should be distributed for payouts.

        If hours_by_worker is provided and total hours for a destination's assigned workers
        is greater than zero, distribute proportionally by hours. Otherwise, fall back to
        equal split among assigned workers.
        """
        if bucket_id not in worker_assignments:
            return {}

        distributions = {}
        assignments = worker_assignments[bucket_id]
        hours_by_worker = hours_by_worker or {}

        for destination, workers in (assignments or {}).items():
            if not workers:
                continue

            # Tip amount keyed by destination name (e.g., "Bartender", "Busser", etc.)
            tip_amount = float(tip_amounts.get(destination, 0.0) or 0.0)
            if tip_amount <= 0:
                continue

            # Compute total hours among assigned workers
            total_hours = 0.0
            worker_hours_map = {}
            for w in workers:
                h = float(hours_by_worker.get(w, 0.0) or 0.0)
                worker_hours_map[w] = h
                total_hours += h

            if total_hours > 0:
                # Proportional by hours
                for w in workers:
                    share = tip_amount * (worker_hours_map.get(w, 0.0) / total_hours)
                    if w not in distributions:
                        distributions[w] = {}
                    distributions[w][destination] = share
            else:
                # Fall back to equal split
                per_worker_amount = tip_amount / len(workers)
                for w in workers:
                    if w not in distributions:
                        distributions[w] = {}
                    distributions[w][destination] = per_worker_amount

        return distributions

    @staticmethod
    def validate_tip_input(tips_dict):
        """Validate tip input values"""
        errors = []
        
        for key, value in tips_dict.items():
            if value < 0:
                errors.append(f"{key} cannot be negative")
                
        return errors

    @staticmethod
    def format_currency(amount):
        """Format amount as currency"""
        return f"${amount:.2f}"

    @staticmethod
    def calculate_total_tips(bartips, servertips, expotips, runnertips):
        """Calculate total payout tips"""
        return bartips + servertips + expotips + runnertips
