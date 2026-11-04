import json
import sqlite3
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: db_inspect.py <nutshell.sqlite3>")
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

    out["dbversions"] = one("select * from dbversions")
    out["tables"] = [r[0] for r in con.execute(
        "select name from sqlite_master where type='table' order by name"
    )]
    out["keysets"] = one(
        "select id, version, unit, active, derivation_path, input_fee_ppk, "
        "amounts, final_expiry from keysets order by valid_from"
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
        "union all select 'pending', count(*) from proofs_pending"
    )
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
