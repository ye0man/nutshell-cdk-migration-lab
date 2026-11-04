import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import httpx


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_db(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def db_summary(path: Path) -> dict:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    out = {}

    def one(sql):
        try:
            return [dict(r) for r in con.execute(sql).fetchall()]
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    out["dbversions"] = one("select * from dbversions")
    out["keysets"] = one(
        "select id, version, unit, active, derivation_path, input_fee_ppk, "
        "final_expiry from keysets order by valid_from"
    )
    out["counts"] = one(
        "select (select count(*) from keysets) as keysets, "
        "(select count(*) from mint_quotes) as mint_quotes, "
        "(select count(*) from melt_quotes) as melt_quotes, "
        "(select count(*) from promises) as promises, "
        "(select count(*) from proofs_used) as proofs_used, "
        "(select count(*) from proofs_pending) as proofs_pending"
    )
    out["mint_quote_states"] = one(
        "select state, count(*) as n from mint_quotes group by state order by state"
    )
    out["melt_quote_states"] = one(
        "select state, count(*) as n from melt_quotes group by state order by state"
    )
    out["proof_states"] = one(
        "select 'used' as state, count(*) as n from proofs_used "
        "union all select 'pending', count(*) as n from proofs_pending"
    )
    out["empty_c_used"] = one(
        "select count(*) as n, coalesce(sum(amount),0) as amount "
        "from proofs_used where c is null or c = ''"
    )
    out["proofs_without_keyset"] = one(
        "select count(*) as n from (select id from proofs_used union all select id from proofs_pending) "
        "where id not in (select id from keysets)"
    )
    out["duplicate_melt_checking_ids"] = one(
        "select checking_id, count(*) as n from melt_quotes "
        "where lower(state) in ('paid','pending') group by checking_id having count(*) > 1"
    )
    con.close()
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--label", default="nutshell")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = Path(args.db)

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
    backup = out_dir / f"{args.label}.sqlite3"
    snapshot_db(db_path, backup)
    meta = {
        "url": args.url,
        "source_db": str(db_path),
        "backup": str(backup),
        "sha256": sha256(backup),
        "db": db_summary(backup),
    }
    (out_dir / f"{args.label}-meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    print(json.dumps(meta["db"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
