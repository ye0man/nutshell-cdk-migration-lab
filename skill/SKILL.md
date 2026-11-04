---
name: nutshell-to-cdk-migration
description: Plan, run, and review a Nutshell mint to CDK migration. Use for "migrate nutshell to cdk", "nutshell mint migration", "Nutshell 0.22 to CDK 0.18", converting a Nutshell mint database, or assessing whether a mint can move to CDK. Covers SQLite/PostgreSQL, seed and keyset preservation, preflight, verification, rollback, and known blockers.
---

# Nutshell -> CDK migration

This skill drives an offline migration from a Nutshell mint (0.20.3-0.22.x) to
CDK v0.18.3 using the ported PR #2016 tool. It is experimental: the subcommand is
not in the stock v0.18.3 release.

Default lab and assets:

```
LAB=C:\Users\jakey\projects\cashu\nutshell-cdk-migration-lab
GUIDE=$LAB\GUIDE.md
PATCHES=$LAB\PATCHES.md
GAPS=$LAB\GAPS.md
REPORTS=$LAB\FIELD-REPORTS.md
BIN=$LAB\patched-cdk\target\debug\cdk-mintd.exe
```

If the paths do not exist, ask the operator for their lab/build location. Do not
invent a different migration procedure.

## Non-negotiables

1. **Offline only.** Stop the Nutshell mint. Never migrate a live database.
2. **Back up first.** Copy the database and working directory; keep the backup
   until verification passes.
3. **Same database engine.** SQLite -> SQLite, PostgreSQL -> PostgreSQL. No
   cross-engine migration.
4. **Preserve the exact signer.** `MINT_MNEMONIC` -> `[info].mnemonic`;
   `MINT_PRIVATE_KEY`/raw seed -> `[info].seed`. Never convert between them.
5. **Never claim unverified support.** LND, CLN, Strike, Spark, NUT-21 auth, and
   large-volume timing are not verified by this skill. Say so.

## Step 1 - Preflight

Run on a copy:

```powershell
python $LAB\scripts\preflight.py --source <sqlite-path-or-pg-url> `
  --json-out preflight.json --md-out preflight.md
```

Check:

- `schema` is 38-42.
- every `keysets[].version` is >= 0.15.0.
- `empty_c_used`: spent proofs with empty C; needs `--allow-empty-c`.
- `orphan_promises` / `orphan_proofs`: needs `--allow-orphans`, after recording.
- `duplicate_melt_checking_ids`: resolve manually; no override.
- `payment_uncertain`: settle pending melts first.
- `null_c_promises` is normal.

If any condition is unexpected, stop and request the sanitized preflight report.

## Step 2 - Map the configuration

Read `$LAB\reference\backend-mapping.md`. Required decisions:

- source and target engine/paths or URLs
- seed mode (`mnemonic` vs `seed`)
- every unit's backend (sat/usd/eur)
- whether pending melts can be settled on the same node
- whether auth is enabled (it is not migrated)

Use `$LAB\reference\nutshell.env.example`,
`$LAB\reference\cdk-sqlite.toml`, and
`$LAB\reference\cdk-postgres.toml` as checklists.

## Step 3 - Build or locate the patched binary

The subcommand and the keyset-only init fix are not in stock v0.18.3. Build from
`$LAB\patched-cdk`:

```powershell
$env:PROTOC = "C:\path\to\protoc.exe"
cargo build -p cdk-mintd --no-default-features `
  --features sqlite,postgres,fakewallet,info-page
```

Do not substitute a stock `cdk-mintd` binary.

## Step 4 - Run the migration

SQLite:

```powershell
& $BIN migrate-nutshell --source <nutshell.sqlite3> `
  --target <new-cdk.sqlite> --allow-empty-c
```

PostgreSQL:

```powershell
& $BIN migrate-nutshell --source <nutshell-pg-url> `
  --target <empty-cdk-pg-url> --tls-mode disable --allow-empty-c
```

Add `--allow-orphans` only if the preflight reported orphans and the operator
accepted the skipped counts. Add `--allow-unknown-schema` only after reviewing
new Nutshell migrations.

Then:

```powershell
& $BIN migrate-nutshell --source ... --target ... --verify-only
```

## Step 5 - Initialize and start CDK

SQLite:

```powershell
& $BIN --work-dir <cdk-dir> config init --existing-mint --file config.toml
& $BIN --work-dir <cdk-dir>
```

PostgreSQL: export `CDK_MINTD_DATABASE=postgres`,
`CDK_MINTD_POSTGRES_URL=...`, `CDK_MINTD_POSTGRES_TLS_MODE=...` first.

Configuration gotchas:

- `mnemonic`/`seed` must be `env:` or `file:` references.
- `[info.quote_ttl]` is a table with `mint_ttl`/`melt_ttl`.
- `[fake_wallet]` is required for the fakewallet backend.
- Stock v0.18.3 rejects a keyset-only DB; the patched build accepts it after
  verifying the signer against keysets.

## Step 6 - Verify

```powershell
python $LAB\scripts\compare_keys.py snapshot\nutshell-keys.json http://127.0.0.1:3338
python $LAB\scripts\verify_states.py --source <nutshell-db> `
  --target <cdk-db> --allow-new-keysets
python $LAB\scripts\verify_wallet.py --url http://127.0.0.1:3338 `
  --mnemonic "<wallet mnemonic>" --db restore.sqlite3 --test-spend
```

For PostgreSQL use `verify_states_pg.py`.

Required results:

- every old keyset's keys byte-identical
- old keysets inactive, new active per unit
- proof states, quote accounting, melt states, promise set match
- NUT-09 restore returns the unspent balance
- old note redeems; the same proof is rejected as already spent
- a small Lightning mint and melt work

Expected, not failures:

- CDK rotates each unit's keyset on first start (64 -> 32 amounts)
- `/v1/info` pubkey changes unless `[mint_info].pubkey` is set to the old value
- restore can include proofs pending a melt; they show `Token Pending`

## Step 7 - Roll back if needed

Stop CDK, restore the Nutshell database and working directory from the cold
backup, restart Nutshell with the original seed and backend, verify keys and
balances. Notes created on CDK after cutover cannot be rolled back.

## Quick hurdle table

| Error | Action |
|---|---|
| `Unsupported Nutshell mint schema version` | Use this port (38-42) or `--allow-unknown-schema` after review |
| `Unsupported Nutshell version: 0.22.x` | Update to the current port; it accepts 0.15.0-0.22.x |
| `Invalid C public key ... found=0` | `--allow-empty-c` (spent only) |
| `promise(s) and ... proof(s) whose keyset is missing` | `--allow-orphans` after recording counts |
| `multiple paid or pending melt quotes` | Resolve duplicates; no override |
| `relation "pubkeys" does not exist` | Use this port; it checks `mint_pubkeys` |
| `Target CDK database ... already exists` | Pick a new SQLite path |
| `does not contain a mint identity` | Use the patched build or seed mint info |
| `info.quote_ttl` type error | Use `[info.quote_ttl]` table |
| `Token Pending` after restore | Pending melt; wait or reconcile |

## Reporting gaps

If a path is not in `GAPS.md`, do not guess. Produce a sanitized `preflight.md`
and a migration log, add an entry using the template in `FIELD-REPORTS.md`, and
mark the claim as unverified.

Never include seeds, mnemonics, macaroons, proof secrets, or raw database dumps.
