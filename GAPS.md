# Gaps and unverified paths

This file is intentionally blunt. A path is "verified" only if the lab actually
ran it against the target versions.

## Verified in this lab

| Path | Evidence |
|---|---|
| Nutshell 0.22.0 (schema 42) -> CDK v0.18.3, SQLite | S1: 71 mint quotes, 20 melt quotes, 924 proofs, 1043 promises; keys identical; NUT-09; redeem; double spend rejected |
| Nutshell 0.22.1 (schema 42) -> CDK v0.18.3, SQLite | S9: 10 mint quotes, 3 melt quotes, 162 proofs, 220 promises; keys identical |
| Nutshell 0.22.0 -> CDK v0.18.3, PostgreSQL | S2: 71 mint quotes, 20 melt quotes, 762 proofs, 949 promises; keys identical; NUT-09; redeem; double spend rejected |
| Nutshell 0.22.0 multi-unit sat/usd/eur, SQLite | S3: 3 keysets, 6 target keysets after rotation, all old keys identical |
| Nutshell 0.21.0 (schema 39), SQLite | S8: 16 mint quotes, 5 melt quotes, 286 proofs, 396 promises |
| Nutshell 0.20.3 (schema 38), SQLite | S7: 17 mint quotes, 5 melt quotes, 298 proofs, 390 promises |
| Empty `C` on spent proofs | S1/S2/S3/S8/S9; `--allow-empty-c` |
| Orphaned keyset rows | Injected into a copy of S1; `--allow-orphans` |
| Duplicate melt payment IDs | Injected; hard failure with the quote's checking ID |
| Proof in both spent and pending tables | Injected; deduplicated and verified |
| Pending and unpaid melt/mint quotes | S1/S2 phases with FakeWallet |
| Keyset rotation on first CDK start | Every run: old keysets inactive, new active, old keys identical |
| Short raw seed import | S7/S8 with `MINT_PRIVATE_KEY`, v0.18.3 warning |
| Config/DB collision avoidance | Explicit `--target` design |

## Not verified

| Path | Why | What to report |
|---|---|---|
| LND gRPC / LND REST | Windows lab cannot run LND | Node version, backend type, whether mint and melt succeed after cutover |
| CLN REST / CLN gRPC | Windows lab cannot run CLN | CLN version, socket path, mint/melt result |
| Strike | No direct CDK 0.18.3 backend | Whether you use `grpc-processor` or stay on Nutshell |
| Spark L2 | No direct CDK 0.18.3 backend | Same as Strike |
| NUT-21 auth migration | Not implemented | Auth database engine, user count, whether you rebuilt auth on CDK |
| Failed melt quote state | Not exercised | Source state, target state, whether funds were released |
| Expired quote semantics | TTL was set to 1 second but expiry fields were not independently audited | Source and target expiry values |
| Multiple historical keysets from a Nutshell-internal rotation | Not exercised; CDK-side rotation is verified | Keyset count, IDs, derivation paths, per-keyset proof counts |
| Large production volume (50k+ proofs) | The lab used 300-900 proofs per run | Row counts, migration duration, memory |
| Custom Nutshell forks | No fork available | Schema diff, extra columns, custom derivation |
| SQLCipher/encrypted SQLite | Not exercised | Whether `--password` opens the target |
| Redis cache | Not migrated; safe to discard | Only if you observe cache-related issues |
| Reverse proxy / TLS / DNS cutover | Not part of the lab | Proxy type, URL, TLS result |
| Management RPC | Not exercised | RPC config and client behaviour |

## Known design limits

- Source and target must use the same database engine.
- Pre-0.15 Nutshell keysets are rejected; their derivation is not supported.
- The migration does not rewrite spent proofs' missing `C`; it stores a
  placeholder for spent rows only.
- The migration does not create a CDK mint-info record. The patched
  `config init --existing-mint` accepts a keyset-only database; stock v0.18.3
  does not.
- The migration is offline. Do not run it against a live database.
