# Nutshell -> CDK migration lab

Lab artifacts for migrating Nutshell mints (0.20.3-0.22.x) to CDK v0.18.3 using
the ported code from closed CDK PR #2016.

Start with:

- [`GUIDE.md`](GUIDE.md) - operator runbook, verification, hurdle catalog
- [`handoff/`](handoff/) - minimal operator package (binary + SQL preflight)
- [`.github/workflows/release-binaries.yml`](.github/workflows/release-binaries.yml)
  - builds `cdk-mintd` for Linux, macOS, and Windows from the patch series
- [`GAPS.md`](GAPS.md) - what is and is not verified
- [`FIELD-REPORTS.md`](FIELD-REPORTS.md) - real reports and a template
- [`PATCHES.md`](PATCHES.md) - changes to CDK v0.18.3
- `patches/` - six `git format-patch` files applying to CDK v0.18.3
- `patched-cdk/` - the built worktree (branch `nutshell-migration-v0.18.3`)
- `skill/SKILL.md` - opencode skill; copy it to
  `~/.config/opencode/skills/nutshell-to-cdk-migration/`

## Lab results

| Run | Nutshell | Schema | Database | Result |
|---|---|---|---|---|
| S1 | 0.22.0 tag (keysets report 0.21.0) | 42 | SQLite | Pass |
| S2 | 0.22.0 tag | 42 | PostgreSQL | Pass |
| S3 | 0.22.0 tag | 42 | SQLite, sat/usd/eur | Pass |
| S9 | 0.22.1 (fixed version bump) | 42 | SQLite | Pass |
| S7 | 0.20.3 | 38 | SQLite, raw seed | Pass |
| S8 | 0.21.0 | 39 | SQLite, raw seed | Pass |

Edge injections: orphan promise, duplicate melt payment ID, proof in both state
tables, empty `C` on spent proofs, pending/unpaid quotes.

## Layout

```
scripts/
  preflight.py            sanitized preflight report (SQLite/PostgreSQL)
  prepare_source_postgres.sql  clean a source copy for migration
  prepare_source_sqlite.sql    clean a source copy for migration
  verify_keyset_ids.py    re-hash served keys to their NUT-02 id
  simulate.py             mint/swap/melt activity profiles
  snapshot.py             API + SQLite snapshot
  snapshot_pg.py          API + pg_dump snapshot
  compare_keys.py         byte-identical keyset comparison
  verify_states.py        SQLite source/target state comparison
  verify_states_pg.py     PostgreSQL source/target state comparison
  verify_wallet.py        NUT-09 restore, redemption, double-spend check
  inject_edges.py         inject orphans, duplicate melts, proof-in-both
  mintctl.ps1             start/stop lab mints on Windows
  db_inspect.py           Nutshell DB summary
  cdk_inspect.py          CDK DB summary (v0.18.3)
  sqlite_query.py         ad-hoc read-only query

reference/
  nutshell.env.example
  cdk-sqlite.toml
  cdk-postgres.toml
  backend-mapping.md

runs/
  S1 S2 S3 S5-* S7 S8       scenario data, snapshots, logs
```

## Build

```powershell
$env:PROTOC = "C:\path\to\protoc.exe"
cargo build -p cdk-mintd --no-default-features `
  --features sqlite,postgres,fakewallet,info-page
```

Binary: `patched-cdk/target/debug/cdk-mintd.exe`.

## Caveats

- The migration subcommand is not in the stock CDK v0.18.3 release.
- LND, CLN, Strike, Spark, NUT-21 auth, and large-volume timing were not tested.
- Nutshell 0.22.0 was published without a version bump; S1-S3 were run on that
  tag and its keysets report 0.21.0. 0.22.1 fixes the bump (S9); use 0.22.1.
- Do not migrate a live database. Freeze, back up, verify, then reopen.
