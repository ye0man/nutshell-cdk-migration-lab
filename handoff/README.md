# Operator handoff

This folder is the minimal package for a mint operator. It does not need the lab,
Python, the activity simulator, FakeWallet, or the reference mints.

## What the migration itself needs

The migration command needs only:

1. the patched `cdk-mintd` binary (see Releases),
2. a stopped Nutshell database,
3. an empty target database of the **same engine** (SQLite or PostgreSQL).

It does **not** need a mint seed, a Lightning backend, `config.toml`, Redis, or the
Nutshell auth database. The migration is a database copy plus verification.

## What still needs configuration

Starting CDK after the migration needs:

- a seed/mnemonic (or remote signatory),
- a CDK `config.toml`,
- one CDK backend per unit,
- working Lightning node access.

The migration tool does not start a mint. The cutover still needs the operator's
normal CDK configuration.

## Run

```bash
# SQLite
cdk-mintd migrate-nutshell \
  --source /path/to/nutshell/mint.sqlite3 \
  --target /var/lib/cdk-mintd/cdk-mintd.sqlite \
  --allow-empty-c

# PostgreSQL
cdk-mintd migrate-nutshell \
  --source 'postgres://nutshell:password@127.0.0.1:5432/nutshell' \
  --target 'postgres://cdk:password@127.0.0.1:5432/cdk_mint' \
  --tls-mode disable \
  --allow-empty-c

# Re-run the independent verification
cdk-mintd migrate-nutshell --source ... --target ... --verify-only
```

## Clean the source copy

Historical mints can carry keysets and rows the migrator skips, which makes the
per-keyset liability check fail. Run the matching script against a **copy** of
the source database before migrating:

- `../scripts/prepare_source_postgres.sql`
- `../scripts/prepare_source_sqlite.sql`

Both are idempotent and run in a transaction. See section 6.5 of the full guide.

## Verify served keys

The migrator does not re-hash the keys the mint will serve. With the migrated
mint running:

```bash
python ../scripts/verify_keyset_ids.py http://127.0.0.1:3338
```

Exit code 1 means do not cut over.

Then initialize CDK configuration with the original seed:

```bash
cdk-mintd --work-dir /var/lib/cdk-mintd \
  config init --existing-mint --file config.toml
cdk-mintd --work-dir /var/lib/cdk-mintd
```

Stock v0.18.3 does not include the `migrate-nutshell` command and rejects a
keyset-only database during `config init`. Use the patched binary from this
repository's Releases, or build it from `patches/`.

## Preflight

Run the read-only SQL in this folder against a copy of the source database:

- `preflight_sqlite.sql`
- `preflight_postgres.sql`

The full operator runbook is in [`../GUIDE.md`](../GUIDE.md).
