"""
Synthetic transaction generator for RecoverAI.
Generates 150-300 transactions following real-world fintech distributions.
Outputs directly into recovery.db and exports to data/transactions.csv.
"""

import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import random
import os
import csv
from datetime import datetime, timedelta
from faker import Faker
import pandas as pd

from src.db import get_connection, init_db, DEFAULT_DB_PATH
from src.constants import (
    FAIL_INSUFFICIENT_FUNDS,
    FAIL_BANK_DECLINED,
    FAIL_GATEWAY_TIMEOUT,
    FAIL_CARD_EXPIRED,
    FAIL_OTP_TIMEOUT,
    FAIL_MANDATE_EXPIRED
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CSV_PATH = DATA_DIR / "transactions.csv"

def generate_transactions(count: int = 200, db_path=None, seed: int = 42) -> pd.DataFrame:
    """
    Generates a synthetic transaction batch and writes to DB and CSV.
    Count defaults to 200 (within PRD range 150-300).
    """
    random.seed(seed)
    fake = Faker('en_IN')
    Faker.seed(seed)

    # Ensure data directory exists
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Initialize / clean DB
    init_db(db_path=db_path, wipe=True)

    # Generate customer pool (~80 unique customers across 200 transactions)
    customer_count = max(40, count // 3)
    customers = []
    for i in range(customer_count):
        cust_id = f"cust_{i+1:03d}"
        cust_name = fake.name()
        # ~5% opted out
        opted_out = (random.random() < 0.05)
        customers.append({
            "customer_id": cust_id,
            "customer_name": cust_name,
            "opted_out": opted_out
        })

    # Failure code probabilities among failures (PRD §6.1)
    # 30% insufficient_funds, 25% bank_declined, 15% gateway_timeout,
    # 15% card_expired, 10% otp_timeout, 5% mandate_expired.
    # We include a small fraction (~4%) of unclassified/unrecognized for LLM fallback testing.
    failure_codes = [
        FAIL_INSUFFICIENT_FUNDS,
        FAIL_BANK_DECLINED,
        FAIL_GATEWAY_TIMEOUT,
        FAIL_CARD_EXPIRED,
        FAIL_OTP_TIMEOUT,
        FAIL_MANDATE_EXPIRED,
        "unrecognized_bank_error",  # edge case for LLM fallback
    ]
    failure_weights = [0.30, 0.25, 0.15, 0.15, 0.09, 0.05, 0.01]

    payment_methods = ["upi", "card", "netbanking", "wallet"]
    method_weights = [0.50, 0.30, 0.12, 0.08]

    now = datetime.now()
    transactions = []

    for i in range(1, count + 1):
        txn_id = f"txn_{i:04d}"
        cust = random.choice(customers)

        # Status distribution: ~65% success, ~29% failed, ~6% abandoned
        status_rand = random.random()
        if status_rand < 0.65:
            status = "success"
        elif status_rand < 0.94:
            status = "failed"
        else:
            status = "abandoned"

        # Channel & B2B distribution: ~10% B2B invoices
        is_b2b = (random.random() < 0.10)
        if is_b2b:
            channel = "b2b_invoice"
            payment_method = "netbanking"
            amount = round(random.uniform(25000, 180000), 2)
            is_subscription = False
        else:
            channel = random.choice(["web", "app"])
            payment_method = random.choices(payment_methods, weights=method_weights)[0]
            # Regular retail amounts (₹199 to ₹8,500)
            amount = round(random.uniform(199, 8500), 2)
            # ~20% of transactions are subscriptions
            is_subscription = (random.random() < 0.20)

        # Timestamp spread over last 30 days
        # For B2B failed invoices, ensure a good portion are > 7 days old to trigger overdue_invoice rule
        if is_b2b and status == "failed":
            days_ago = random.uniform(8, 28)
        elif status == "failed":
            # Some >24 hours, some <24 hours
            days_ago = random.uniform(0.5, 25)
        elif status == "abandoned":
            days_ago = random.uniform(0.1, 15)
        else:
            days_ago = random.uniform(0.1, 30)

        created_at = now - timedelta(days=days_ago)

        # Failure code and retry count logic
        if status == "success":
            failure_code = None
            retry_count = random.choice([0, 1, 2])
        elif status == "abandoned":
            failure_code = None
            retry_count = 0
        else:  # failed
            if is_subscription and random.random() < 0.40:
                failure_code = FAIL_MANDATE_EXPIRED
            else:
                failure_code = random.choices(failure_codes, weights=failure_weights)[0]

            # ~80% of failed payments have retry_count = 0 (never retried)
            retry_count = 0 if random.random() < 0.80 else random.choice([1, 2])

        transactions.append({
            "transaction_id": txn_id,
            "customer_id": cust["customer_id"],
            "customer_name": cust["customer_name"],
            "amount": amount,
            "payment_method": payment_method,
            "status": status,
            "failure_code": failure_code,
            "is_subscription": 1 if is_subscription else 0,
            "channel": channel,
            "created_at": created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "retry_count": retry_count,
            "customer_opted_out": 1 if cust["opted_out"] else 0,
            "recovered": 0
        })

    df = pd.DataFrame(transactions)

    # Save to SQLite
    conn = get_connection(db_path)
    df.to_sql("transactions", conn, if_exists="append", index=False)
    conn.close()

    # Save to CSV
    df.to_csv(CSV_PATH, index=False)

    return df

if __name__ == "__main__":
    print("Generating synthetic transactions batch...")
    df = generate_transactions(count=200)
    print(f"Successfully generated {len(df)} transactions.")
    print(f"Status distribution:\n{df['status'].value_counts(normalize=True)}")
    print(f"\nFailure code distribution:\n{df[df['status'] == 'failed']['failure_code'].value_counts(dropna=False)}")
    print(f"\nSubscriptions: {df['is_subscription'].sum()} / {len(df)}")
    print(f"B2B Invoices: {(df['channel'] == 'b2b_invoice').sum()} / {len(df)}")
    print(f"Opted out customers: {df['customer_opted_out'].sum()} / {len(df)}")
    print(f"Exported to DB and {CSV_PATH}")
