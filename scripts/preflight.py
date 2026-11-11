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
        "empty_amounts": one(
            "select count(*) n from keysets "
            "where amounts is null or trim(amounts) in ('', '[]')"
        ),
        "keysets_unrepresentable": one(
            "select id, version, derivation_path from keysets where not ("
            "((length(id) = 16 and id not glob '*[^0-9a-fA-F]*') or "
            "(length(id) = 66 and lower(substr(id, 1, 2)) = '01' "
            "and id not glob '*[^0-9a-fA-F]*')) "
            "and derivation_path like 'm/%' "
            "and not (version glob '0.[0-9].*' or version glob '0.1[0-4].*'))"
        ),
        "null_mint_states": one(
            "select count(*) n from mint_quotes where state is null"
        ),
        "null_melt_states": one(
            "select count(*) n from melt_quotes where state is null"
        ),
        "placeholder_mint_checking_ids": one(
            "select count(*) n from mint_quotes where checking_id is null "
            "or trim(checking_id) = '' or lower(checking_id) in ('none', 'null')"
        ),
        "duplicate_mint_checking_ids": one(
            "select checking_id, count(*) n from mint_quotes "
            "where checking_id is not null and trim(checking_id) <> '' "
            "and lower(checking_id) not in ('none', 'null') "
            "group by checking_id having count(*) > 1"
        ),
        "invalid_promise_rows": one(
            "select count(*) n from promises where c_ is not null and ("
            "b_ is null or length(b_) <> 66 "
            "or lower(substr(b_, 1, 2)) not in ('02', '03') "
            "or b_ glob '*[^0-9a-fA-F]*' "
            "or length(c_) <> 66 "
            "or lower(substr(c_, 1, 2)) not in ('02', '03') "
            "or c_ glob '*[^0-9a-fA-F]*')"
        ),
        "invalid_pending_proofs": one(
            "select count(*) n from proofs_pending where c is null "
            "or trim(c) = '' or length(c) <> 66 "
            "or lower(substr(c, 1, 2)) not in ('02', '03') "
            "or c glob '*[^0-9a-fA-F]*'"
        ),
        "invalid_spent_proofs": one(
            "select count(*) n from proofs_used where c is not null "
            "and trim(c) <> '' and (length(c) <> 66 "
            "or lower(substr(c, 1, 2)) not in ('02', '03') "
            "or c glob '*[^0-9a-fA-F]*')"
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
        "empty_amounts": await fetch(
            "select count(*) n from keysets "
            "where amounts is null or btrim(amounts) in ('', '[]')"
        ),
        "keysets_unrepresentable": await fetch(
            "select id, version, derivation_path from keysets where not ("
            "(id ~* '^[0-9a-f]{16}$' or id ~* '^01[0-9a-f]{64}$') "
            "and derivation_path like 'm/%' "
            "and version !~ '^0\\.([0-9]|1[0-4])(\\.|$)')"
        ),
        "null_mint_states": await fetch(
            "select count(*) n from mint_quotes where state is null"
        ),
        "null_melt_states": await fetch(
            "select count(*) n from melt_quotes where state is null"
        ),
        "placeholder_mint_checking_ids": await fetch(
            "select count(*) n from mint_quotes where checking_id is null "
            "or btrim(checking_id) = '' "
            "or lower(checking_id) in ('none', 'null')"
        ),
        "duplicate_mint_checking_ids": await fetch(
            "select checking_id, count(*) n from mint_quotes "
            "where checking_id is not null and btrim(checking_id) <> '' "
            "and lower(checking_id) not in ('none', 'null') "
            "group by checking_id having count(*) > 1"
        ),
        "invalid_promise_rows": await fetch(
            "select count(*) n from promises where c_ is not null and ("
            "b_ is null or b_ !~* '^0[23][0-9a-f]{64}$' "
            "or c_ !~* '^0[23][0-9a-f]{64}$')"
        ),
        "invalid_pending_proofs": await fetch(
            "select count(*) n from proofs_pending where c is null "
            "or btrim(c) = '' or c !~* '^0[23][0-9a-f]{64}$'"
        ),
        "invalid_spent_proofs": await fetch(
            "select count(*) n from proofs_used where c is not null "
            "and btrim(c) <> '' and c !~* '^0[23][0-9a-f]{64}$'"
        ),
        "int4_amount_columns": await fetch(
            "select table_name, column_name, data_type "
            "from information_schema.columns where table_schema = 'public' "
            "and column_name in ('amount', 'fee_reserve', 'amount_paid', 'amount_issued') "
            "and data_type in ('integer', 'smallint') "
            "order by table_name, column_name"
        ),
        "expiry_out_of_int4_range": await fetch(
            "select count(*) n from melt_quotes where case "
            "when expiry::text ~ '^[0-9]+$' "
            "then expiry::text::bigint > 2147483647 else false end"
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

