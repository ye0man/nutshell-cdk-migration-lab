import argparse
import asyncio
import hashlib
import json
import subprocess
from pathlib import Path

import asyncpg
import httpx


async def summary(pg_url: str) -> dict:
    conn = await asyncpg.connect(pg_url)
    try:
        out = {}

        async def fetch(sql):
            try:
                return [dict(r) for r in await conn.fetch(sql)]
            except Exception as exc:  # noqa: BLE001
                return {"error": str(exc)}

        out["dbversions"] = await fetch("select * from dbversions")
        out["keysets"] = await fetch(
            "select id, version, unit, active, derivation_path, input_fee_ppk, "
            "final_expiry from keysets order by valid_from"
        )
        out["counts"] = await fetch(
            "select (select count(*) from keysets) as keysets, "
            "(select count(*) from mint_quotes) as mint_quotes, "
            "(select count(*) from melt_quotes) as melt_quotes, "
            "(select count(*) from promises) as promises, "
            "(select count(*) from proofs_used) as proofs_used, "
            "(select count(*) from proofs_pending) as proofs_pending"
        )
        out["mint_quote_states"] = await fetch(
            "select state, count(*) as n from mint_quotes group by state order by state"
        )
        out["melt_quote_states"] = await fetch(
            "select state, count(*) as n from melt_quotes group by state order by state"
        )
        out["proof_states"] = await fetch(
            "select 'used' as state, count(*) as n from proofs_used "
            "union all select 'pending', count(*) as n from proofs_pending"
        )
        out["empty_c_used"] = await fetch(
            "select count(*) as n, coalesce(sum(amount),0) as amount "
            "from proofs_used where c is null or c = ''"
        )
        out["proofs_without_keyset"] = await fetch(
            "select count(*) as n from (select id from proofs_used union all select id from proofs_pending) "
            "where id not in (select id from keysets)"
        )
        out["duplicate_melt_checking_ids"] = await fetch(
            "select checking_id, count(*) as n from melt_quotes "
            "where lower(state) in ('paid','pending') group by checking_id having count(*) > 1"
        )
        return out
    finally:
        await conn.close()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--pg-url", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--label", default="nutshell")
    parser.add_argument("--pg-dump", required=True)
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with httpx.Client(base_url=args.url, timeout=10) as client:
        info = client.get("/v1/info").json()
        keysets = client.get("/v1/keysets").json()
        keys = {}
        for keyset in keysets.get("keysets", []):
            keyset_id = keyset["id"]
            response = client.get(f"/v1/keys/{keyset_id}")
            if response.status_code == 404:
                response = client.get("/v1/keys", params={"keyset_id": keyset_id})
            keys[keyset_id] = response.json()

    (out_dir / f"{args.label}-info.json").write_text(
        json.dumps(info, indent=2), encoding="utf-8"
    )
    (out_dir / f"{args.label}-keysets.json").write_text(
        json.dumps(keysets, indent=2), encoding="utf-8"
    )
    (out_dir / f"{args.label}-keys.json").write_text(
        json.dumps(keys, indent=2), encoding="utf-8"
    )

    dump_path = out_dir / f"{args.label}.dump"
    subprocess.run(
        [args.pg_dump, "-Fc", "-f", str(dump_path), "-d", args.pg_url],
        check=True,
    )
    meta = {
        "url": args.url,
        "pg_url": args.pg_url,
        "dump": str(dump_path),
        "sha256": sha256(dump_path),
        "db": await summary(args.pg_url),
    }
    (out_dir / f"{args.label}-meta.json").write_text(
        json.dumps(meta, indent=2, default=str), encoding="utf8"
    )
    print(json.dumps(meta["db"], indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
