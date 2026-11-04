import argparse
import asyncio
import json
import random
import sys
import time
from pathlib import Path

from cashu.core.base import MintQuoteState
from cashu.wallet.wallet import Wallet


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


async def open_wallet(url: str, db: Path, name: str, unit: str) -> Wallet:
    db.parent.mkdir(parents=True, exist_ok=True)
    wallet = await Wallet.with_db(url=url, db=str(db), name=name, unit=unit)
    await wallet.load_mint()
    await wallet.load_proofs()
    return wallet


async def wait_paid(wallet: Wallet, quote_id: str, timeout: float = 30.0) -> object:
    deadline = time.monotonic() + timeout
    quote = None
    while time.monotonic() < deadline:
        quote = await wallet.get_mint_quote(quote_id)
        if quote.state_val == MintQuoteState.paid:
            return quote
        await asyncio.sleep(0.2)
    return quote


async def mint_once(wallet: Wallet, amount: int) -> bool:
    quote = await wallet.request_mint(amount)
    quote = await wait_paid(wallet, quote.quote)
    if quote is None or quote.state_val != MintQuoteState.paid:
        log(f"mint quote {quote.quote[:12]} did not settle: {quote.state_val}")
        return False
    await wallet.mint(amount, quote.quote)
    await wallet.load_proofs()
    return True


async def swap_once(wallet: Wallet, amount: int) -> bool:
    await wallet.load_proofs()
    if sum(p.amount for p in wallet.proofs) < amount + 200:
        return False
    await wallet.split(wallet.proofs, amount)
    await wallet.load_proofs()
    return True


async def melt_once(wallet: Wallet, invoice_wallet: Wallet, amount: int) -> dict:
    invoice_quote = await invoice_wallet.request_mint(amount)
    melt_quote = await wallet.melt_quote(invoice_quote.request)
    needed = melt_quote.amount + melt_quote.fee_reserve + 200
    await wallet.load_proofs()
    if sum(p.amount for p in wallet.proofs) < needed:
        return {"result": "no-balance", "quote": melt_quote.quote}
    _, inputs = await wallet.split(wallet.proofs, needed)
    try:
        result = await wallet.melt(
            inputs, invoice_quote.request, melt_quote.fee_reserve, melt_quote.quote
        )
        outcome = {
            "result": str(getattr(result, "state", result)),
            "quote": melt_quote.quote,
            "amount": melt_quote.amount,
            "fee_reserve": melt_quote.fee_reserve,
        }
    except Exception as exc:  # noqa: BLE001
        outcome = {"result": f"error:{exc}", "quote": melt_quote.quote}
    await wallet.load_proofs()
    return outcome


async def phase_normal(args, wallets, invoice_wallet, summary):
    rng = random.Random(args.seed)
    for index, wallet in enumerate(wallets):
        for _ in range(args.mints):
            amount = rng.randrange(args.amount_min, args.amount_max + 1)
            await mint_once(wallet, amount)
        for _ in range(args.swaps):
            await swap_once(wallet, rng.randrange(10, 200))
        for _ in range(args.melts):
            await wallet.load_proofs()
            balance = sum(p.amount for p in wallet.proofs)
            if balance < 1200:
                await mint_once(wallet, 1500)
                await wallet.load_proofs()
                balance = sum(p.amount for p in wallet.proofs)
            melt_amount = min(
                rng.randrange(args.amount_min, args.amount_max + 1),
                max(args.amount_min, balance // 2),
            )
            outcome = await melt_once(wallet, invoice_wallet, melt_amount)
            summary["melts"].append({"wallet": index, **outcome})
        for _ in range(args.pni):
            amount = rng.randrange(args.amount_min, args.amount_max + 1)
            quote = await wallet.request_mint(amount)
            quote = await wait_paid(wallet, quote.quote)
            summary["paid_not_issued"].append(
                {
                    "wallet": index,
                    "quote": quote.quote,
                    "amount": amount,
                    "state": str(quote.state_val),
                }
            )
        summary["wallets"].append(
            {
                "index": index,
                "db": str(Path(args.wallet_dir) / f"wallet-{index}.sqlite3"),
                "mnemonic": wallet.mnemonic,
                "balance": sum(p.amount for p in wallet.proofs),
                "proofs": len(wallet.proofs),
            }
        )
        log(
            f"wallet {index}: balance={sum(p.amount for p in wallet.proofs)} "
            f"proofs={len(wallet.proofs)}"
        )


async def phase_unpaid(args, wallets, invoice_wallet, summary):
    rng = random.Random(args.seed)
    for index, wallet in enumerate(wallets):
        for _ in range(args.unpaid):
            amount = rng.randrange(args.amount_min, args.amount_max + 1)
            quote = await wallet.request_mint(amount)
            summary["unpaid_quotes"].append(
                {"wallet": index, "quote": quote.quote, "amount": amount}
            )
        log(f"wallet {index}: created {args.unpaid} unpaid quotes")


async def phase_pending(args, wallets, invoice_wallet, summary):
    rng = random.Random(args.seed)
    for index, wallet in enumerate(wallets):
        for _ in range(args.pending):
            outcome = await melt_once(
                wallet, invoice_wallet, rng.randrange(args.amount_min, args.amount_max + 1)
            )
            summary["melt_attempts"].append({"wallet": index, **outcome})
        log(f"wallet {index}: pending melt attempts done")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--invoice-url", required=True)
    parser.add_argument("--wallet-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--unit", default="sat")
    parser.add_argument("--phase", default="normal", choices=["normal", "unpaid", "pending", "failed"])
    parser.add_argument("--wallets", type=int, default=10)
    parser.add_argument("--mints", type=int, default=3)
    parser.add_argument("--swaps", type=int, default=1)
    parser.add_argument("--melts", type=int, default=1)
    parser.add_argument("--pni", type=int, default=1)
    parser.add_argument("--unpaid", type=int, default=3)
    parser.add_argument("--pending", type=int, default=3)
    parser.add_argument("--amount-min", type=int, default=21)
    parser.add_argument("--amount-max", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    wallet_dir = Path(args.wallet_dir)
    wallets = []
    for index in range(args.wallets):
        wallets.append(
            await open_wallet(
                args.url, wallet_dir / f"wallet-{index}.sqlite3", f"wallet-{index}", args.unit
            )
        )
    invoice_wallet = await open_wallet(
        args.invoice_url, wallet_dir / "invoice-wallet.sqlite3", "invoices", args.unit
    )

    summary = {
        "phase": args.phase,
        "url": args.url,
        "unit": args.unit,
        "wallets": [],
        "melts": [],
        "paid_not_issued": [],
        "unpaid_quotes": [],
        "melt_attempts": [],
    }

    if args.phase == "normal":
        await phase_normal(args, wallets, invoice_wallet, summary)
    elif args.phase == "unpaid":
        await phase_unpaid(args, wallets, invoice_wallet, summary)
    else:
        await phase_pending(args, wallets, invoice_wallet, summary)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
