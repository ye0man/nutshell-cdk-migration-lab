# Field reports

Real operator results. Add a new entry at the top. Attach the sanitized
`preflight.md`, migration output, and verification summary. Never attach seeds,
mnemonics, macaroons, proof secrets, or raw database dumps.

---

## 2026-10 - gorrdy - Nutshell 0.21.0 (field)

Source: [CDK PR #2016 comment](https://github.com/cashubtc/cdk/pull/2016#issuecomment-6019897180)

Setup:

- PostgreSQL test mint (`nutshell.cashu.cz`) with real LND, migrated with the
  original PR branch, then run on CDK `main`.
- SQLite snapshot of a production mint: ~52k proofs, ~58k promises, ~22k mint
  quotes, ~5k melt quotes; fakewallet in an isolated sandbox.

Worked after workarounds:

- `/v1/keys` byte-identical for all keysets.
- Proof states and quote states matched.
- NUT-09 restore returned identical signatures.
- Existing wallet could swap, melt, and mint over Lightning.
- Old-keyset notes redeemed on CDK; double spends rejected.

Blockers:

1. Version/schema gate accepted only 0.20.3 / schema 38; 0.21.0 is schema 39.
2. PostgreSQL target URL was not resolved from `env:`.
3. PostgreSQL `verify_keyset_id` expected a `pubkeys` table Nutshell does not have.
4. SQLite config database and migration target were the same file.
5. Spent proofs with `c=''` (nutshell#1199); 3,711 proofs / 8.3M sat affected.
6. Orphaned keyset rows made verification counts fail and rolled back.
7. The branch config format was older than main's.

Observed after cutover: keyset rotation (64 -> 32 amounts) and a new
`/v1/info` pubkey.

---

## 2026-11 - lab - Nutshell 0.22.1 / 0.22.0 / 0.21.0 / 0.20.3 -> CDK v0.18.3

Environment: native Windows, SQLite and PostgreSQL 16.6, FakeWallet, ported PR
#2016 code on v0.18.3. Nutshell 0.22.0 was published without the version bump and
self-reports 0.21.0; 0.22.1 corrects the bump. Both use schema 42.

| Run | Nutshell | Schema | DB | Result |
|---|---|---|---|---|
| S1 | 0.22.0 tag | 42 | SQLite | Pass |
| S2 | 0.22.0 tag | 42 | PostgreSQL | Pass |
| S3 | 0.22.0 tag | 42 | SQLite, sat/usd/eur | Pass |
| S9 | 0.22.1 | 42 | SQLite | Pass |
| S7 | 0.20.3 | 38 | SQLite, raw seed | Pass |
| S8 | 0.21.0 | 39 | SQLite, raw seed | Pass |

S1 details: 71 mint quotes (issued/paid/unpaid), 20 melt quotes (paid/pending),
924 proofs (868 spent / 56 pending), 1,043 promises, 48 spent proofs with empty
`C` (11,603 sat). Migration and `--verify-only` passed with
`--allow-empty-c`. Old keyset keys byte-identical; all record sets matched.
NUT-09 restore returned 2,949 sat with 9 unspent and 5 pending proofs; a 1-sat
spend succeeded and the same proofs were rejected as already spent.

S2 details: 71 mint quotes, 20 melt quotes (10 paid / 6 pending / 4 unpaid),
762 proofs, 949 promises, 59 spent proofs with empty `C` (14,661 sat). Pass.

S3 details: sat/usd/eur keysets, 53 mint quotes, 6 melt quotes, 681 proofs, 865
promises. All three old keysets byte-identical; CDK created three new active
keysets.

S9 details: Nutshell 0.22.1 (the corrected version bump), 10 mint quotes, 3 melt
quotes, 162 proofs, 220 promises. Keyset version `0.22.1`; keys identical and all
record sets matched. This confirms the gate accepts 0.22.x patch versions.

S7/S8 details: legacy `MINT_PRIVATE_KEY` raw seeds. CDK `[info].seed` reproduced
the historical keysets; `config init` warned about a short seed but succeeded.
All keys and record sets matched.

Additional injections:

- Orphan promise: refused without `--allow-orphans`; skipped and verified with it.
- Duplicate melt `checking_id`: refused with the offending ID.
- Proof in both `proofs_used` and `proofs_pending`: deduplicated and verified.

Not tested: LND, CLN, Strike, Spark, NUT-21 auth migration, large-volume timing.

---

## Template

```
## YYYY-MM - <name or handle> - Nutshell <version> -> CDK <version>

Source / fork:
Database: sqlite | postgres | other
Units:
Backend before: FakeWallet | LndRPC | LndRest | CLNRest | Strike | SparkL2
Backend after:
Schema (dbversions):
Keyset versions:
Row counts: keysets / mint quotes / melt quotes / promises / proofs
Warnings from preflight: empty C / orphans / duplicate melts / other
Migration flags:
Migration result:
Verification:
  - old keysets identical:
  - states match:
  - NUT-09 restore:
  - redeem old note:
  - double spend rejected:
  - mint/melt over Lightning:
Surprises:
Blockers:
```
