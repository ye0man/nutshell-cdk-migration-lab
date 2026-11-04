import argparse
import sqlite3
import sys

GENERATOR = "0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument(
        "--kind",
        required=True,
        choices=["orphan-promise", "duplicate-melt", "proof-in-both", "all"],
    )
    args = parser.parse_args()
    con = sqlite3.connect(args.db)
    try:
        if args.kind in ("orphan-promise", "all"):
            con.execute(
                "insert into promises (amount, id, b_, c_, created, mint_quote, swap_id, order_index) "
                "values (1, '00deadbeefdeadbeef', ?, ?, strftime('%s','now'), null, null, 0)",
                (GENERATOR, GENERATOR),
            )
        if args.kind in ("duplicate-melt", "all"):
            con.execute(
                "insert into melt_quotes (quote, method, request, checking_id, unit, amount, "
                "fee_reserve, created_time, paid_time, fee_paid, proof, state, expiry, attempt, "
                "melt_lock, melt_lock_expires_at, payment_uncertain) "
                "select '01deadbeef-0000-0000-0000-000000000001', method, request, checking_id, "
                "unit, amount, fee_reserve, created_time, paid_time, fee_paid, proof, state, "
                "expiry, attempt, melt_lock, melt_lock_expires_at, payment_uncertain "
                "from melt_quotes where state = 'PAID' limit 1"
            )
        if args.kind in ("proof-in-both", "all"):
            con.execute(
                "insert into proofs_pending (amount, c, secret, y, id, created) "
                "select amount, c, secret, y, id, created from proofs_used limit 1"
            )
        con.commit()
    finally:
        con.close()
    print(f"injected {args.kind} into {args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
