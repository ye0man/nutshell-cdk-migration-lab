import json
import sqlite3
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: cdk_inspect.py <cdk-mintd.sqlite>")
        return 2
    path = Path(sys.argv[1])
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    out = {"db": str(path)}

    def one(sql):
        try:
            return [dict(r) for r in con.execute(sql).fetchall()]
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    out["tables"] = [r[0] for r in con.execute(
        "select name from sqlite_master where type='table' order by name"
    )]
    out["migrations"] = one("select * from _sqlx_migrations order by version")
    out["keyset"] = one(
        "select id, unit, active, derivation_path, input_fee_ppk, final_expiry "
        "from keyset order by valid_from"
    )
    out["counts"] = one(
        "select (select count(*) from keyset) as keysets, "
        "(select count(*) from mint_quote) as mint_quotes, "
        "(select count(*) from melt_quote) as melt_quotes, "
        "(select count(*) from blind_signature) as blind_signatures, "
        "(select count(*) from proof) as proofs, "
        "(select count(*) from keyset_amounts) as keyset_amounts"
    )
    out["mint_quote_states"] = one(
        "select state, count(*) as n from mint_quote group by state order by state"
    )
    out["melt_quote_states"] = one(
        "select state, count(*) as n from melt_quote group by state order by state"
    )
    out["proof_states"] = one(
        "select state, count(*) as n from proof group by state order by state"
    )
    out["keyset_amounts"] = one(
        "select keyset_id, total_issued, total_redeemed from keyset_amounts order by keyset_id"
    )
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
