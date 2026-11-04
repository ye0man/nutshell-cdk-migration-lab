import asyncio
import sys
from pathlib import Path

from cashu.core.base import MintQuoteState
from cashu.wallet.wallet import Wallet


async def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:13339"
    db = sys.argv[2] if len(sys.argv) > 2 else "wallet.sqlite3"
    invoice_url = sys.argv[3] if len(sys.argv) > 3 else "http://127.0.0.1:13340"
    invoice_db = sys.argv[4] if len(sys.argv) > 4 else "invoice-wallet.sqlite3"
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    Path(invoice_db).parent.mkdir(parents=True, exist_ok=True)

    invoice_wallet = await Wallet.with_db(url=invoice_url, db=invoice_db, name="invoices")
    await invoice_wallet.load_mint()

    wallet = await Wallet.with_db(url=url, db=db, name="sim")
    await wallet.load_mint()

    quote = await wallet.request_mint(1000)
    print("mint quote", quote.quote[:16], "state", quote.state_val)
    await asyncio.sleep(2)
    quote = await wallet.get_mint_quote(quote.quote)
    print("mint quote state after wait", quote.state_val)
    if quote.state_val != MintQuoteState.paid:
        raise SystemExit(f"expected paid, got {quote.state_val}")

    proofs = await wallet.mint(1000, quote.quote)
    await wallet.load_proofs()
    print("balance after mint", wallet.balance, "proofs", len(wallet.proofs))

    keep, send = await wallet.split(wallet.proofs, 100)
    await wallet.load_proofs()
    print("after swap balance", wallet.balance, "proofs", len(wallet.proofs))

    melt_target = await invoice_wallet.request_mint(50)
    await asyncio.sleep(2)
    melt_quote = await wallet.melt_quote(melt_target.request)
    print(
        "melt quote",
        melt_quote.quote[:16],
        "amount",
        melt_quote.amount,
        "fee_reserve",
        melt_quote.fee_reserve,
        "state",
        melt_quote.state,
    )

    _, melt_inputs = await wallet.split(
        wallet.proofs, melt_quote.amount + melt_quote.fee_reserve + 100
    )
    print("melt inputs", sum(p.amount for p in melt_inputs))
    result = await wallet.melt(
        melt_inputs, melt_target.request, melt_quote.fee_reserve, melt_quote.quote
    )
    print("melt result", result)
    await wallet.load_proofs()
    print("final balance", wallet.balance, "proofs", len(wallet.proofs))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
