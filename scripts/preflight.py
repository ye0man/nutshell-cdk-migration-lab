import argparse
import asyncio
import json
import sqlite3
import sys
from pathlib import Path


def sqlite_report(path: str) -> dict:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    out = {"source": path, "engine": "sqlite"}

    def one(sql):
        try:
            return [dict(r) for r in con.execute(sql).fetchall()]
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    out["schema"] = one("select version from dbversions where db = 'mint'")
    out["keysets"] = one(
        "select id, version, unit, active, derivation_path, input_fee_ppk, "
        "amounts, final_expiry from keysets order by valid_from"
    )
    out["counts"] = one(
        "select (select count(*) from keysets) keysets, "
        "(select count(*) from mint_quotes) mint_quotes, "
        "(select count(*) from melt_quotes) melt_quotes, "
        "(select count(*) from promises) promises, "
        "(select count(*) from proofs_used) proofs_used, "
        "(select count(*) from proofs_pending) proofs_pending"
    )
    out["mint_quote_states"] = one(
        "select state, count(*) n from mint_quotes group by state order by state"
    )
    out["melt_quote_states"] = one(
        "select state, count(*) n from melt_quotes group by state order by state"
    )
    out["warnings"] = {
        "empty_c_used": one(
            "select count(*) n, coalesce(sum(amount),0) amount from proofs_used "
            "where c is null or c = ''"
        ),
        "orphan_promises": one(
            "select count(*) n from promises where id not in (select id from keysets)"
        ),
        "orphan_proofs": one(
            "select count(*) n from (select id from proofs_used union all "
            "select id from proofs_pending) where id not in (select id from keysets)"
        ),
        "duplicate_melt_checking_ids": one(
            "select checking_id, count(*) n from melt_quotes "
            "where lower(state) in ('paid','pending') group by checking_id "
            "having count(*) > 1"
        ),
        "null_c_promises": one("select count(*) n from promises where c_ is null"),
        "proof_in_both_tables": one(
            "select count(*) n from proofs_pending p where exists "
            "(select 1 from proofs_used u where u.y = p.y)"
        ),
        "payment_uncertain": one(
            "select count(*) n from melt_quotes where payment_uncertain = 1"
        ),
    }
    if isinstance(out["warnings"]["payment_uncertain"], dict):
        out["warnings"]["payment_uncertain"] = {
            "note": "column not present in this schema"
        }
    con.close()
    return out



async def pg_report(url: str) -> dict:
    import asyncpg

    con = await asyncpg.connect(url)
    out = {"source": url, "engine": "postgres"}

    async def fetch(sql):
        try:
            return [dict(r) for r in await con.fetch(sql)]
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    out["schema"] = await fetch("select version from dbversions where db = 'mint'")
    out["keysets"] = await fetch(
        "select id, version, unit, active, derivation_path, input_fee_ppk, "
        "amounts, final_expiry from keysets order by valid_from"
    )
    out["counts"] = await fetch(
        "select (select count(*) from keysets) keysets, "
        "(select count(*) from mint_quotes) mint_quotes, "
        "(select count(*) from melt_quotes) melt_quotes, "
        "(select count(*) from promises) promises, "
        "(select count(*) from proofs_used) proofs_used, "
        "(select count(*) from proofs_pending) proofs_pending"
    )
    out["mint_quote_states"] = await fetch(
        "select state, count(*) n from mint_quotes group by state order by state"
    )
    out["melt_quote_states"] = await fetch(
        "select state, count(*) n from melt_quotes group by state order by state"
    )
    out["warnings"] = {
        "empty_c_used": await fetch(
            "select count(*) n, coalesce(sum(amount),0) amount from proofs_used "
            "where c is null or c = ''"
        ),
        "orphan_promises": await fetch(
            "select count(*) n from promises where id not in (select id from keysets)"
        ),
        "orphan_proofs": await fetch(
            "select count(*) n from (select id from proofs_used union all "
            "select id from proofs_pending) p where p.id not in (select id from keysets)"
        ),
        "duplicate_melt_checking_ids": await fetch(
            "select checking_id, count(*) n from melt_quotes "
            "where lower(state) in ('paid','pending') group by checking_id "
            "having count(*) > 1"
        ),
        "null_c_promises": await fetch("select count(*) n from promises where c_ is null"),
        "proof_in_both_tables": await fetch(
            "select count(*) n from proofs_pending p where exists "
            "(select 1 from proofs_used u where u.y = p.y)"
        ),
        "payment_uncertain": await fetch(
            "select count(*) n from melt_quotes where payment_uncertain = 1"
        ),
    }
    if isinstance(out["warnings"]["payment_uncertain"], dict):
        out["warnings"]["payment_uncertain"] = {
            "note": "column not present in this schema"
        }
    await con.close()
    return out



def markdown(report: dict) -> str:
    lines = ["# Nutshell mint preflight report", ""]
    lines.append(f"- Source: `{report['source']}`")
    lines.append(f"- Engine: **{report['engine']}**")
    lines.append(f"- Nutshell schema: `{report.get('schema')}`")
    lines.append("")
    lines.append("## Counts")
    lines.append("```json")
    lines.append(json.dumps(report.get("counts"), indent=2, default=str))
    lines.append("```")
    lines.append("## Quote states")
    lines.append("```json")
    lines.append(json.dumps(report.get("mint_quote_states"), indent=2, default=str))
    lines.append(json.dumps(report.get("melt_quote_states"), indent=2, default=str))
    lines.append("```")
    lines.append("## Keysets")
    lines.append("```json")
    lines.append(json.dumps(report.get("keysets"), indent=2, default=str))
    lines.append("```")
    lines.append("## Warnings")
    lines.append("```json")
    lines.append(json.dumps(report.get("warnings"), indent=2, default=str))
    lines.append("```")
    lines.append("")
    lines.append(
        "This report contains no seed, mnemonic, macaroon, or proof secrets. "
        "Review the warnings before choosing migration flags."
    )
    return "\n".join(lines) + "\n"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--json-out")
    parser.add_argument("--md-out")
    args = parser.parse_args()

    if args.source.startswith("postgres://") or args.source.startswith("postgresql://"):
        report = await pg_report(args.source)
    else:
        report = sqlite_report(args.source)

    payload = json.dumps(report, indent=2, default=str)
    if args.json_out:
        Path(args.json_out).write_text(payload, encoding="utf-8")
    else:
        print(payload)
    if args.md_out:
        Path(args.md_out).write_text(markdown(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

