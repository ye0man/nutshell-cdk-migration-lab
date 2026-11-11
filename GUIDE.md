# Migrating a Nutshell mint to CDK v0.18.3

**Status: experimental.** This guide is based on the closed, unmerged CDK PR
[#2016](https://github.com/cashubtc/cdk/pull/2016), ported onto CDK **v0.18.3**
and extended for Nutshell **0.20.3 through 0.22.x**. It is not an official CDK
release feature. Treat the first cutover as a supervised migration with a
maintenance window, a backup, and a rollback plan.

The lab behind this guide ran on Windows with SQLite, PostgreSQL, and the
FakeWallet backend. LND, CLN, Strike, and Spark were **not** exercised at
runtime. The backend mapping section says what is known and what is not.

### Standalone use

The migration command is self-contained. It needs only:

1. the patched `cdk-mintd` binary,
2. a stopped Nutshell database,
3. an empty target database of the same engine.

It does **not** need Python, the lab scripts, a seed, a Lightning backend, or a
`config.toml`. It is a database copy plus verification. The lab scripts are
optional preflight and verification aids.

Starting CDK after the migration is the part that needs a seed, configuration,
and one backend per unit. The minimal operator package is in [`handoff/`](handoff/).
Prebuilt binaries are produced by
[`.github/workflows/release-binaries.yml`](.github/workflows/release-binaries.yml).

---

## 1. What is tested

| Area | Result |
|---|---|
| Nutshell 0.22.1 (schema 42) | Migrated, verified |
| Nutshell 0.22.0 tag (schema 42) | Migrated, verified |
| Nutshell 0.21.0 (schema 39) | Migrated, verified |
| Nutshell 0.20.3 (schema 38) | Migrated, verified |
| SQLite source and target | Verified |
| PostgreSQL source and target | Verified |
| sat / usd / eur units | Migrated, keys identical |
| Empty `C` on spent proofs | Handled with `--allow-empty-c` |
| Orphaned keyset rows | Detected; handled with `--allow-orphans` |
| Duplicate melt payment IDs | Rejected with an actionable error |
| Proof present in both spent and pending tables | Deduplicated and verified |
| NUT-09 restore | Verified |
| Redeeming old notes, double-spend rejection | Verified |
| Keyset-id guard (`verify_keyset_ids.py`) | Verified against a migrated mint |
| NULL states, literal `None` lookup ids, empty `amounts` | Verified on a mutated SQLite copy |
| PostgreSQL int4 columns / Y2038 expiry | Normalized in code; not exercised live |
| LND / CLN / Strike / Spark runtime | **Not tested** |
| NUT-21 auth database | **Not migrated** |

> Nutshell 0.22.0 was published without the version bump and self-reports
> `0.21.0`. **0.22.1 fixes the bump** and is the release to use. Both use schema
> 42, and the migrator accepts any 0.22.x keyset version. Always confirm the
> schema with `dbversions`; do not infer it from the release tag.

---

## 2. What the migration copies

Copied:

- keysets, including derivation paths, units, fees, amount lists, expiry
- mint quotes and their paid/issued amounts
- melt quotes and states
- promises (blind signatures and pending blinded messages)
- spent and pending proofs
- keyset liabilities and payment lookup IDs

The migration keeps each keyset's original amount list. Keysets CDK cannot
represent (legacy/base58 ids, non-BIP32 derivation paths, pre-0.15 keysets) are
skipped, and their promises and proofs are skipped with them. Run the
source-cleaning SQL in section 6.5 to remove them up front. Leaving their
balances behind can make the per-keyset liability check fail.

Not copied:

- the Nutshell auth database (NUT-21 users, keysets, promises)
- the NUT-19 response cache (safe to discard)
- Lightning node state, channels, macaroons, or backend configuration
- management RPC state
- mint metadata and limits: re-enter these in the CDK TOML

---

## 3. Feasibility checklist

Do not start if any answer is "no" or "unknown":

- You have a **cold backup** of the Nutshell database and its working directory.
- You know whether the mint used `MINT_MNEMONIC` or `MINT_PRIVATE_KEY`, and you
  have the exact value.
- You know the Nutshell schema version (`dbversions`) and the per-keyset version.
- Every unit has a CDK-compatible backend. Strike and Spark units do not have a
  direct CDK 0.18.3 backend.
- You can pause minting and melting for the cutover.
- You can keep the Lightning node and backend reachable at the same identity, or
  you have drained pending melts.
- You accept that the CDK code path is a port of an unmerged PR.

### Custom Nutshell forks

If the mint runs a fork, diff its schema and keyset derivation against upstream
before migrating. Extra tables are usually harmless; extra columns that the
migrator reads, custom derivation paths, or a customized auth ledger are not.
Collect the preflight report and open an issue before proceeding.

---

## 4. Preflight

Run the report against a **copy** of the live database. It contains no seed,
mnemonic, macaroon, or proof secrets.

```bash
python scripts/preflight.py \
  --source /path/to/nutshell/mint.sqlite3 \
  --json-out preflight.json \
  --md-out preflight.md
```

For PostgreSQL:

```bash
python scripts/preflight.py \
  --source 'postgres://nutshell:password@127.0.0.1:5432/nutshell' \
  --json-out preflight.json
```

Review these fields:

- `schema`: must be 38, 39, 40, 41, or 42.
- `keysets[].version`: accepted from 0.15.0 through 0.22.x. Pre-0.15 keysets are
  not supported.
- `empty_c_used`: spent proofs with an empty `C`. The original value is lost;
  use `--allow-empty-c` only for spent proofs.
- `orphan_promises` / `orphan_proofs`: rows whose keyset is missing. These cannot
  be signed. Use `--allow-orphans` only after recording the counts.
- `duplicate_melt_checking_ids`: resolve these before migrating. The tool
  intentionally refuses to guess which quote is authoritative.
- `null_c_promises`: normal for pending change outputs; the migrator stores them
  as blinded messages.
- `payment_uncertain`: pending melts whose backend state was uncertain. Settle or
  reconcile them before cutover.
- `empty_amounts`: keysets with an empty amount list. The migrator supplies a
  default; if that default is wrong the served keys no longer hash to the keyset
  id. Repair in section 6.5 and run the keyset-id guard in section 10.
- `keysets_unrepresentable`: keysets that will be skipped (legacy id, non-BIP32
  path, pre-0.15). Prune their rows on the copy (section 6.5).
- `null_mint_states` / `null_melt_states`: NULL quote states. The patched port
  maps these to UNPAID; the SQL also backfills them.
- `placeholder_mint_checking_ids` / `duplicate_mint_checking_ids`: NULL, empty,
  or literal `None` lookup ids collide with CDK's unique `request_lookup_id`.
  Normalize and deduplicate on the copy.
- `invalid_promise_rows`, `invalid_pending_proofs`, `invalid_spent_proofs`: rows
  the migrator skips but which still count toward source liabilities, causing
  the liability check to fail. Remove them on the copy.
- PostgreSQL only: `int4_amount_columns` lists `amount`/`fee_reserve` columns
  stored as int4, and `expiry_out_of_int4_range` counts melt quotes beyond the
  2038 ceiling. The patched port casts the reads and clamps expiry; confirm both
  are clean anyway.

The raw SQL for the same checks is in `scripts/preflight.py`; run it read-only.

---

## 5. Preserve the signing identity

The migration copies keyset metadata, but CDK must be able to **re-derive** the
same private keys. Choose exactly one mode:

| Nutshell setup | CDK config |
|---|---|
| `MINT_MNEMONIC` (0.22.x) | `[info].mnemonic = "env:CDK_MINTD_MNEMONIC"` |
| `MINT_PRIVATE_KEY` (0.20.x/0.21.x and older) | `[info].seed = "env:CDK_MINTD_SEED"` |
| raw seed used directly | `[info].seed = "env:CDK_MINTD_SEED"` |
| remote signatory | `[signatory]`; do not put a local seed in the mint |

Rules:

- Use the exact original value. Do not convert a raw seed to a mnemonic or the
  reverse.
- `config init --existing-mint` verifies the signer against historical keysets.
  A wrong seed fails there, before users are exposed.
- v0.18.0 rejects raw seeds shorter than 32 bytes. Use v0.18.3 (or v0.18.1+),
  which accepts them for an existing mint with a warning.
- The advertised mint pubkey is metadata. Record the old `/v1/info` pubkey and,
  if clients depend on it, set `[mint_info].pubkey` to that value. This does not
  change keyset signatures.

### Verify the signer without printing it

Nutshell derives each keyset with BIP32 over the raw UTF-8 bytes of the seed.
CDK reproduces that only when the value is supplied verbatim as `[info].seed`.
A BIP39 mnemonic path (or a seed-file conversion) derives different keys, which
is why a raw seed must never be converted to a mnemonic or the reverse.

You can confirm the value without disclosing it by comparing hashes:

```bash
# PostgreSQL: hash the stored seed and the value you intend to configure.
printf '%s' "$CDK_SEED" | md5sum
psql "$NUTSHELL_URL" -Atc \
  "select md5(seed) from keysets where derivation_path like 'm/%' limit 1"
```

The two hashes must match. For SQLite, read `keysets.seed` if your Nutshell
version stores it and hash it with the same tool. `config init --existing-mint`
is still the final authority: it verifies the signer against historical keysets.

---

## 6. Choose the target database

The source and target must be the **same engine**. Cross-engine migration is not
supported.

### SQLite

- Stop Nutshell first.
- The target path must not exist. The migrator writes a staging database and
  renames it into place only after verification succeeds.
- A common trap in the original PR was reading the config from the same SQLite
  file it wanted to write. This port takes an explicit `--target`, so the
  collision cannot happen.

### PostgreSQL

- Create an empty CDK database.
- Pass the target URL explicitly. If your config stores `env:CDK_MINTD_POSTGRES_URL`,
  resolve it in the shell before running the migrator; the original PR did not.
- The tool applies the CDK schema and refuses a non-empty target.

---

## 6.5 Clean the source copy (recommended)

Run this against the **copy**, never the live database. The migrator was
validated on clean test mints; a production database carries history it will
skip or reject. The cleaning scripts make the migrator's row counts and
per-keyset liabilities line up with what it can actually represent.

```bash
# PostgreSQL
psql 'postgres://nutshell:password@127.0.0.1:5432/nutshell_copy' \
  -v ON_ERROR_STOP=1 -f scripts/prepare_source_postgres.sql

# SQLite
sqlite3 nutshell-copy.sqlite3 < scripts/prepare_source_sqlite.sql
```

Both scripts are idempotent and run in a transaction. Review the preview
`SELECT`s at the top before you commit if you want to inspect the changes. They:

1. Repair keysets whose `amounts` list is empty (Nutshell keysets span 2^0 .. 2^63).
2. Normalize NULL, empty, and literal `None` payment lookup ids.
3. Deduplicate paid/pending melt quotes per `checking_id` (keep PAID, then the
   earliest; rename the rest with `-dup-<quote>`).
4. Backfill NULL quote states to UNPAID.
5. Clamp melt-quote expiry beyond the int4 (2038) ceiling (PostgreSQL).
6. Prune keysets CDK cannot represent, and their promises, proofs, and pubkeys.
7. Remove promise and proof rows the migrator cannot parse but which still count
   toward source liabilities.
8. Run `ANALYZE`.

One case cannot be detected in SQL: a `b_` or `c_` value that is valid compressed
hex but not a valid curve point. The migrator logs it as `invalid B_` and skips
it, which leaves its amount in the source liability. If you see such a log line,
delete that row by its `b_` value on the copy and re-run.

Rows whose keyset is missing entirely are still orphans. Use `--allow-orphans`
for those only, after recording the counts.

---

## 7. Run the migration

The binary must be the patched `cdk-mintd` from this lab (the subcommand is not in
stock v0.18.3).

```bash
# SQLite
cdk-mintd migrate-nutshell \
  --source /path/to/nutshell/mint.sqlite3 \
  --target /var/lib/cdk-mintd/cdk-mintd.sqlite \
  --allow-empty-c
```

```bash
# PostgreSQL
export CDK_MINTD_POSTGRES_URL='postgres://cdk:password@127.0.0.1:5432/cdk_mint'
cdk-mintd migrate-nutshell \
  --source 'postgres://nutshell:password@127.0.0.1:5432/nutshell' \
  --target "$CDK_MINTD_POSTGRES_URL" \
  --tls-mode disable \
  --allow-empty-c
```

Flags:

| Flag | Use |
|---|---|
| `--verify-only` | Re-run the independent verification without writing |
| `--allow-empty-c` | Replace an empty `C` on **spent** proofs with the generator |
| `--allow-orphans` | Skip promises/proofs whose keyset row is missing |
| `--allow-unknown-schema` | Accept a schema outside 38-42 after review |

Always run `--verify-only` after a successful migration and before starting CDK.

The migration itself does not touch the Nutshell database. It opens SQLite in
read-only mode for verification.

### What the patched port normalizes on read

The port tolerates common historical data without needing the section 6.5 SQL:

- NULL mint/melt quote states become UNPAID.
- NULL, empty, or literal `None` `checking_id` values fall back to the quote id,
  so they do not collide on CDK's unique `request_lookup_id`.
- PostgreSQL reads `amount`, `fee_reserve`, `amount_paid`, `amount_issued`, and
  `order_index` through `::bigint`, so int4 source columns do not fail.
- An empty keyset `amounts` list falls back to the full 64-denomination set on
  both SQLite and PostgreSQL.
- Melt-quote expiry is clamped to the int4 ceiling (2038).
- Duplicate paid/pending melt quotes with a real payment id still abort. That is
  intentional: run the dedup step in section 6.5.

`--verify-only` checks row counts, quote accounting, promise ordering, and
per-keyset liabilities. It does **not** re-hash the public keys the mint will
serve. Run the keyset-id guard in section 10 with the mint serving.

---

## 8. Initialize the CDK configuration

The patched build includes one behavioural change from stock v0.18.3: an
existing mint whose database contains keysets but no mint-info record is accepted
for `config init --existing-mint`. Stock v0.18.3 refuses it with
`does not contain a mint identity`, because Nutshell has no CDK mint-info record.
The signer is still verified against historical keysets, so this does not weaken
the identity check.

### SQLite

```bash
cdk-mintd config validate --file /etc/cdk-mintd/config.toml
cdk-mintd --work-dir /var/lib/cdk-mintd \
  config init --existing-mint --file /etc/cdk-mintd/config.toml
cdk-mintd --work-dir /var/lib/cdk-mintd
```

### PostgreSQL

```bash
export CDK_MINTD_DATABASE=postgres
export CDK_MINTD_POSTGRES_URL='postgres://cdk:password@127.0.0.1:5432/cdk_mint'
export CDK_MINTD_POSTGRES_TLS_MODE=disable

cdk-mintd config validate --file /etc/cdk-mintd/config.toml
cdk-mintd --work-dir /var/lib/cdk-mintd \
  config init --existing-mint --file /etc/cdk-mintd/config.toml
cdk-mintd --work-dir /var/lib/cdk-mintd
```

Configuration details that commonly trip operators:

- `[info].mnemonic` and `[info].seed` must be `env:...` or `file:/absolute/path`
  references, not literal strings.
- `info.quote_ttl` is a **table**:
  ```toml
  [info.quote_ttl]
  mint_ttl = 600
  melt_ttl = 120
  ```
- The fake-wallet backend needs a `[fake_wallet]` section even if only one unit
  is enabled.
- For PostgreSQL, the bootstrap environment variables must match the document.
- `config show` prints the stored document; `config export --file ...` makes a
  portable copy.

See `reference/cdk-sqlite.toml` and `reference/cdk-postgres.toml`.

---

## 9. What to expect on first start

1. **Keyset rotation.** CDK keysets use 32 amounts; Nutshell uses 64. On first
   start CDK rotates each unit's active keyset. The old keyset stays present and
   inactive, and remains valid for spending. `/v1/keysets` shows the new active
   keyset.
2. **New `/v1/info` pubkey** unless you set `[mint_info].pubkey` to the old value.
3. **Pending melt reconciliation.** CDK tries to reconcile pending quotes against
   its backend. With FakeWallet they may stay pending. With a real node, settle or
   cancel them before cutover.
4. **NUT-09 restore includes pending proofs.** A restore can return proofs that are
   pending a melt. Wallets see `Token Pending` until the melt resolves. This is
   expected, not data loss.
5. **Old notes remain spendable** because the old keysets and promises are
   preserved.

### Keyset issuance policy

The migrated keysets stay present, inactive, and spendable. New issuance uses a
new CDK keyset. In v0.18.3 that is a 32-amount V1 keyset by default.

If your wallet fleet accepts NUT-02 v2 ids (`01`-prefix), set this in `[info]`
to rotate to a V2 keyset deterministically:

```toml
use_keyset_v2 = true
```

Confirm wallet support before cutover. If any wallet in the fleet rejects v2
ids, leave the setting unset.

---

## 10. Verification checklist

Run these before reopening the mint.

### Keys and keysets

- Run the keyset-id guard while the mint is serving. It fetches every advertised
  keyset, recomputes the NUT-02 id from the served public keys, and fails if the
  set does not match. This is independent of the source snapshot and catches a
  truncated amount list that byte-comparison would miss.

  ```bash
  python scripts/verify_keyset_ids.py http://127.0.0.1:3338
  # Optional: also require byte-identity with the source mint
  python scripts/verify_keyset_ids.py http://127.0.0.1:3338 https://mint.example.com
  ```

  Exit code 1 means do not open the mint. The guard accepts the legacy Nutshell
  v2 calculation that hashed an explicit zero expiry.

- Fetch `/v1/keys/{id}` for every old keyset; compare all public keys with the
  pre-migration snapshot. In the lab all old keysets were byte-identical.
- `/v1/keysets` must list every old keyset as inactive, plus the new active keyset
  per unit.
- Units and `input_fee_ppk` must match.

Helper: `python scripts/compare_keys.py snapshot/nutshell-keys.json http://127.0.0.1:3338`

### States and liabilities

- Proof states (SPENT / PENDING / UNSPENT), mint quote paid/issued amounts, and
  melt quote states must match the source.
- Promise count and per-keyset liabilities must match.

Helpers:

```bash
python scripts/verify_states.py --source nutshell.sqlite3 --target cdk-mintd.sqlite --allow-new-keysets
python scripts/verify_states_pg.py --source postgres://.../nutshell --target postgres://.../cdk --allow-new-keysets
```

### Wallet behaviour

- Restore a wallet from its mnemonic against CDK; unspent balance should match.
- Redeem a proof from the old keyset; it should succeed.
- Re-submit the same proof; it must fail with `Token Already Spent`.

Helper: `python scripts/verify_wallet.py --url http://127.0.0.1:3338 --mnemonic "..." --db restore.sqlite3 --test-spend`

### Operations

- Mint and melt a small amount over Lightning.
- Confirm the node pubkey and channels are the same node you started with.
- Check logs for signer, database, or backend errors.
- Confirm auth (if enabled) behaves as expected; auth data is not migrated.

---

## 11. Rollback

The migration does not modify the Nutshell database. Roll back by:

1. Stopping CDK.
2. Restoring the Nutshell database and working directory from the cold backup.
3. Restarting Nutshell with the original seed and backend.
4. Verifying keys, keysets, and balances before reopening.

If users minted new notes on CDK after cutover, those notes cannot be rolled back
to Nutshell. Keep the maintenance window closed until verification passes.

---

## 12. Hurdle catalog

| Symptom | Cause | Action |
|---|---|---|
| `Unsupported Nutshell mint schema version 42` | PR gate only knew 0.20.3/38 | Use this port (38-42) or review the schema and use `--allow-unknown-schema` |
| `Unsupported Nutshell version: 0.22.1` | An older build of this port capped keysets at 0.22.0 | Update to the current port; it accepts 0.15.0-0.22.x |
| `Invalid C public key ... found=0` | Nutshell melt inputs store `c=''` (nutshell#1199) | `--allow-empty-c`; original C is unrecoverable |
| `source has N rows, target has M` after skip | Orphaned keyset rows counted in verification | `--allow-orphans` |
| `multiple paid or pending melt quotes for checking_id` | Duplicate payment lookup IDs | Resolve the duplicate quotes before migrating; no override |
| `relation "pubkeys" does not exist` (PostgreSQL) | PR verification assumed a table Nutshell does not have | Use this port; it checks `mint_pubkeys` and skips empty tables |
| `Target CDK database ... already exists` | SQLite target must be new | Choose a new path; do not pre-create it |
| `env:` URL not resolved | Original PR used the config value as-is | Resolve the URL in the shell and pass it explicitly |
| `does not contain a mint identity` | Stock v0.18.3 expects CDK mint info | Use this port's keyset-only init, or seed CDK mint info first |
| `Config` validation rejects literal mnemonic | v0.18 requires secret references | Use `env:` or `file:` |
| `info.quote_ttl` type error | It is a TOML table, not an integer | Use `[info.quote_ttl] mint_ttl/melt_ttl` |
| `Token Pending` after restore | Restore includes proofs pending a melt | Wait for the melt to settle; checkstate shows the real state |
| New `/v1/info` pubkey | CDK derives its own info pubkey | Set `[mint_info].pubkey` to the old value if needed |
| Old keyset inactive after start | Expected rotation 64 -> 32 | Old keyset remains valid for spending |
| Auth users missing | Auth database is separate and not migrated | Plan a separate auth migration |
| `cannot convert Option<i64> and int4` (PostgreSQL) | `amount`/`fee_reserve` stored as int4 | Use this port (casts reads), or widen the columns on the copy |
| Wallet rejects a keyset / served keys do not match id | Empty or short `amounts` list | Repair in section 6.5; run `verify_keyset_ids.py` |
| `duplicate key value violates unique constraint` on `request_lookup_id` | NULL/empty/`None` or duplicate `checking_id` | Normalize and deduplicate in section 6.5 |
| `Error converting Number, expecting type expiry` | Melt expiry beyond int4 (Y2038) | Port clamps expiry; also clamp in section 6.5 |
| `multiple paid or pending melt quotes for checking_id` | Duplicate real payment ids | Deduplicate in section 6.5 |
| Migration aborts reading a NULL quote state | Older row has NULL state | Port maps NULL to UNPAID; backfill in section 6.5 |
| `per-keyset liabilities differ` | Skipped unparseable rows or pruned keysets | Clean rows and keysets in section 6.5 |
| Legacy/base58 keyset silently skipped | Id is not NUT-02 hex | Prune its rows in section 6.5; keep the base58 mint separate |

---

## 13. Backend changes

See `reference/backend-mapping.md`. Summary:

- FakeWallet -> `fakewallet` (tested).
- LND RPC -> `lnd` gRPC (same node).
- LND REST -> `lnd` gRPC (CDK has no REST backend).
- CLN REST -> `cln` gRPC socket (CDK has no REST backend).
- Strike and Spark L2 have no direct CDK 0.18.3 backend.

Do not change node identity with pending melts. Settle them first.

---

## 14. Reporting gaps

If your setup is not covered, attach `preflight.md`, the `prepare_source_*`
preview counts, the migration output, and the `verify_keyset_ids.py` result to
a field report. Do not attach seeds, mnemonics, macaroons, proof secrets, or raw
database dumps. The preflight report is designed to be safe to share.

See `GAPS.md` and `FIELD-REPORTS.md`.
