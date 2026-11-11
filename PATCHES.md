# Patch series: Nutshell migration on CDK v0.18.3

The working tree is `patched-cdk/`, a detached worktree of CDK v0.18.3. The
changes are a port of the closed PR
[#2016](https://github.com/cashubtc/cdk/pull/2016), adapted to the v0.18.3 APIs
and extended to Nutshell 0.20.3-0.22.x.

## Changes

1. **Order-aware inserts** (`cdk-common`, `cdk-sql-common`)
   - Re-add `add_blinded_messages_with_order` and
     `add_blind_signatures_with_order`. v0.18.3 removed them, but migration needs
     to preserve the original `order_index` of promises.

2. **SQLite migrator** (`cdk-sqlite/src/mint/migrate.rs`)
   - Port the PR reader/writer onto v0.18.3.
   - Schema gate accepts 38-42.
   - Per-keyset version gate accepts 0.15.0-0.22.x.
   - `MigrationOptions` for `--allow-orphans`, `--allow-empty-c`,
     `--allow-unknown-schema`.
   - Empty `C` on spent proofs becomes the secp256k1 generator; pending proofs
     with an empty `C` still fail.
   - Orphan-aware source counts and order queries.

3. **PostgreSQL migrator** (`cdk-postgres/src/migrate.rs`)
   - Same port and options.
   - Local `connect_client` using the crate TLS policy.
   - `verify_keyset_id` reads `mint_pubkeys` (or `pubkeys`) and skips empty or
     missing tables instead of failing on real Nutshell databases.
   - Orphan-aware verification.

4. **CLI and routing** (`cdk-mintd`)
   - `cdk-mintd migrate-nutshell` with `--source`, `--target`, `--tls-mode`,
     `--verify-only`, `--allow-orphans`, `--allow-empty-c`,
     `--allow-unknown-schema`.
   - Explicit target path/URL avoids the original PR's config-DB/target-DB
     collision.

5. **Keyset-only existing-mint init** (`cdk-mintd/src/config_service.rs`)
   - `config init --existing-mint` accepts a database that has keysets but no
     CDK mint-info record. The signer is still verified against historical
     keysets. Stock v0.18.3 rejects this with `does not contain a mint identity`.

6. **Docs and tests**
   - `docs/nutshell-migration.md`.
   - Existing parser/gate tests updated for `MigrationOptions`.
   - `cargo test -p cdk-sqlite --lib mint::migrate` passes.
   - Validated against Nutshell 0.22.0 (tag, schema 42), 0.22.1 (schema 42),
     0.21.0 (schema 39), and 0.20.3 (schema 38).

7. **Historical-data normalization** (SQLite and PostgreSQL)
   - NULL mint/melt quote states map to UNPAID instead of failing the read.
   - NULL, empty, or literal `None` `checking_id` values fall back to the quote
     id, avoiding collisions on CDK's unique `request_lookup_id`.
   - The duplicate-melt guard ignores those placeholders but still aborts on a
     real repeated payment id.

8. **PostgreSQL type tolerance**
   - `amount`, `fee_reserve`, `amount_paid`, `amount_issued`, `order_index`,
     `input_fee_ppk`, and `final_expiry` are read through `::bigint`, so int4
     source columns do not fail tokio-postgres deserialization.
   - Melt-quote expiry is clamped to the int4 (2038) ceiling before insert.

9. **Complete keyset amount fallback**
   - An empty or invalid `amounts` list now falls back to 64 denominations
     (2^0 .. 2^63) on PostgreSQL as well as SQLite. The previous PostgreSQL
     fallback of 32 could serve keys that no longer hash to the keyset id.

10. **Operator tooling**
    - `scripts/verify_keyset_ids.py` re-hashes served keys to their NUT-02 id.
    - `scripts/prepare_source_postgres.sql` and `prepare_source_sqlite.sql`
      clean a source copy for the cases above.

Patch files: `patches/0001` through `patches/0005` are the base port; the
historical-data fixes above are in `patches/0006-fix-migrate-historical-data.patch`.

## Build on Windows

The migration build does not need LND/CLN/BDK features. `cdk-signatory` still
requires `protoc`.

```powershell
$env:PROTOC = "C:\path\to\protoc.exe"
cargo build -p cdk-mintd --no-default-features `
  --features sqlite,postgres,fakewallet,info-page
```

The binary is `patched-cdk/target/debug/cdk-mintd.exe` (or `release`).

## Not included

- LND/CLN/Strike/Spark runtime tests.
- NUT-21 auth database migration.
- A forward port to CDK `main`.
- An upstream PR.
