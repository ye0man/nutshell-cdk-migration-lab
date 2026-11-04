import argparse
import asyncio
import sys

import asyncpg


async def rows(conn, sql):
    return [dict(r) for r in await conn.fetch(sql)]


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--allow-new-keysets", action="store_true")
    args = parser.parse_args()

    source = await asyncpg.connect(args.source)
    target = await asyncpg.connect(args.target)
    failures = []

    source_keysets = {
        r["id"]: (r["unit"], r["input_fee_ppk"])
        for r in await rows(source, "select id, unit, input_fee_ppk from keysets")
    }
    target_keysets = {
        r["id"]: (r["unit"], r["input_fee_ppk"])
        for r in await rows(target, "select id, unit, input_fee_ppk from keyset")
    }
    if set(source_keysets) - set(target_keysets):
        failures.append(f"missing keysets: {sorted(set(source_keysets)-set(target_keysets))}")
    extra = set(target_keysets) - set(source_keysets)
    if extra and not args.allow_new_keysets:
        failures.append(f"unexpected new keysets: {sorted(extra)}")
    for keyset_id in set(source_keysets) & set(target_keysets):
        if source_keysets[keyset_id] != target_keysets[keyset_id]:
            failures.append(
                f"keyset metadata differs for {keyset_id}: "
                f"{source_keysets[keyset_id]} != {target_keysets[keyset_id]}"
            )

    def mint_state(paid, issued, state=None):
        if state is not None:
            return str(state).upper()
        if issued and issued > 0:
            return "ISSUED"
        if paid and paid > 0:
            return "PAID"
        return "UNPAID"

    source_quotes = {}
    for r in await rows(
        source, "select quote, state, amount_paid, amount_issued from mint_quotes"
    ):
        source_quotes[r["quote"]] = (
            mint_state(r["amount_paid"], r["amount_issued"], r["state"]),
            r["amount_paid"] or 0,
            r["amount_issued"] or 0,
        )
    target_quotes = {}
    for r in await rows(target, "select id, amount_paid, amount_issued from mint_quote"):
        target_quotes[r["id"]] = (
            mint_state(r["amount_paid"], r["amount_issued"]),
            r["amount_paid"] or 0,
            r["amount_issued"] or 0,
        )
    if set(source_quotes) != set(target_quotes):
        failures.append(
            f"mint quote IDs differ: missing={len(set(source_quotes)-set(target_quotes))} "
            f"extra={len(set(target_quotes)-set(source_quotes))}"
        )
    for quote_id in set(source_quotes) & set(target_quotes):
        if source_quotes[quote_id] != target_quotes[quote_id]:
            failures.append(
                f"mint quote differs {quote_id}: {source_quotes[quote_id]} != {target_quotes[quote_id]}"
            )

    source_melts = {
        r["quote"]: (str(r["state"]).upper(), r["amount"], r["fee_reserve"])
        for r in await rows(source, "select quote, state, amount, fee_reserve from melt_quotes")
    }
    target_melts = {
        r["id"]: (str(r["state"]).upper(), r["amount"], r["fee_reserve"])
        for r in await rows(target, "select id, state, amount, fee_reserve from melt_quote")
    }
    if set(source_melts) != set(target_melts):
        failures.append(
            f"melt quote IDs differ: missing={len(set(source_melts)-set(target_melts))} "
            f"extra={len(set(target_melts)-set(source_melts))}"
        )
    for quote_id in set(source_melts) & set(target_melts):
        if source_melts[quote_id] != target_melts[quote_id]:
            failures.append(
                f"melt quote differs {quote_id}: {source_melts[quote_id]} != {target_melts[quote_id]}"
            )

    source_proofs = {
        r["y"].lower(): ("SPENT", r["amount"])
        for r in await rows(source, "select y, amount from proofs_used")
    }
    for r in await rows(source, "select y, amount from proofs_pending"):
        source_proofs.setdefault(r["y"].lower(), ("PENDING", r["amount"]))
    target_proofs = {
        r["y"].lower(): (str(r["state"]).upper(), r["amount"])
        for r in await rows(target, "select encode(y, 'hex') as y, state, amount from proof")
    }
    if set(source_proofs) != set(target_proofs):
        failures.append(
            f"proof Y set differs: missing={len(set(source_proofs)-set(target_proofs))} "
            f"extra={len(set(target_proofs)-set(source_proofs))}"
        )
    for y in set(source_proofs) & set(target_proofs):
        if source_proofs[y] != target_proofs[y]:
            failures.append(f"proof differs {y}: {source_proofs[y]} != {target_proofs[y]}")

    source_promises = {
        r["b_"].lower(): (r["id"], r["amount"])
        for r in await rows(source, "select b_, id, amount from promises")
    }
    target_promises = {
        r["b"].lower(): (r["keyset_id"], r["amount"])
        for r in await rows(
            target,
            "select encode(blinded_message, 'hex') as b, keyset_id, amount from blind_signature",
        )
    }
    if set(source_promises) != set(target_promises):
        failures.append(
            f"promise B_ set differs: missing={len(set(source_promises)-set(target_promises))} "
            f"extra={len(set(target_promises)-set(source_promises))}"
        )
    for b in set(source_promises) & set(target_promises):
        if source_promises[b] != target_promises[b]:
            failures.append(f"promise differs {b}: {source_promises[b]} != {target_promises[b]}")

    print(f"keysets: {len(source_keysets)} source, {len(target_keysets)} target")
    print(f"mint quotes: {len(source_quotes)} source, {len(target_quotes)} target")
    print(f"melt quotes: {len(source_melts)} source, {len(target_melts)} target")
    print(f"proofs: {len(source_proofs)} source, {len(target_proofs)} target")
    print(f"promises: {len(source_promises)} source, {len(target_promises)} target")
    if failures:
        print("\nFAILURES:")
        for failure in failures[:50]:
            print(f"- {failure}")
        if len(failures) > 50:
            print(f"... {len(failures) - 50} more")
        return 1
    print("\nAll compared records match.")
    await source.close()
    await target.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
