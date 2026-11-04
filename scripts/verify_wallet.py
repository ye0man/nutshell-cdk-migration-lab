import argparse
import asyncio
import json
import sys
from pathlib import Path

from cashu.core.base import ProofSpentState
from cashu.wallet.wallet import Wallet


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--mnemonic", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--expected-balance", type=int, default=-1)
    parser.add_argument("--restore-to", type=int, default=5)
    parser.add_argument("--test-spend", action="store_true")
    args = parser.parse_args()

    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)
    if db.exists():
        db.unlink()

    wallet = await Wallet.with_db(url=args.url, db=str(db), name="restore")
    await wallet.restore_wallet_from_mnemonic(
        args.mnemonic, to=args.restore_to, batch=25
    )
    await wallet.load_proofs()
    balance = sum(p.amount for p in wallet.proofs)
    print(f"restored balance={balance} proofs={len(wallet.proofs)}")
    if args.expected_balance >= 0 and balance != args.expected_balance:
        print(
            f"BALANCE MISMATCH: expected {args.expected_balance}, got {balance}"
        )
        return 1

    if args.test_spend and wallet.proofs:
        state_response = await wallet.check_proof_state(wallet.proofs)
        spendable = [
            proof
            for proof, state in zip(wallet.proofs, state_response.states)
            if state.state == ProofSpentState.unspent
        ]
        print(f"checkstate: {len(spendable)} unspent of {len(wallet.proofs)} proofs")
        if not spendable:
            print("no unspent proofs to redeem")
            return 0
        original = list(spendable)
        keep, send = await wallet.split(spendable, 1)
        await wallet.load_proofs()
        print(
            f"redeemed old notes: split 1 sat, remaining balance="
            f"{sum(p.amount for p in wallet.proofs)}"
        )
        try:
            await wallet.split(original, 1)
        except Exception as exc:  # noqa: BLE001
            print(f"double spend rejected: {exc}")
            return 0
        print("DOUBLE SPEND WAS ACCEPTED")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
