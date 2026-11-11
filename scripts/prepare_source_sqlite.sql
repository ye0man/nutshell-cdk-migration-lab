-- Prepare a *copy* of a Nutshell SQLite database for
-- `cdk-mintd migrate-nutshell`.
--
-- Run this only against a copied database. Never against live production.
-- The migration is offline: stop Nutshell, copy the database, clean the copy,
-- migrate from the copy.
--
-- The migrator normalizes several of these cases while reading, so this file is
-- defense-in-depth: it also keeps the migrator's row-count and per-keyset
-- liability checks aligned with the source.
--
-- Idempotent. Run with: sqlite3 copy.sqlite3 < prepare_source_sqlite.sql
-- The migration target must be empty when you run it.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Preview keysets CDK cannot represent.
-- ---------------------------------------------------------------------------
SELECT id, version, derivation_path, amounts
FROM keysets
WHERE NOT (
        (
            (length(id) = 16 AND id NOT GLOB '*[^0-9a-fA-F]*')
            OR (
                length(id) = 66
                AND lower(substr(id, 1, 2)) = '01'
                AND id NOT GLOB '*[^0-9a-fA-F]*'
            )
        )
    AND derivation_path LIKE 'm/%'
    AND NOT (version GLOB '0.[0-9].*' OR version GLOB '0.1[0-4].*')
);

-- ---------------------------------------------------------------------------
-- 2. Repair empty or invalid amount lists (2^0 .. 2^63).
--    SQLite integers are signed 64-bit, so 2^63 is written as text.
-- ---------------------------------------------------------------------------
UPDATE keysets
SET amounts = (
    WITH RECURSIVE seq(i) AS (
        SELECT 0
        UNION ALL
        SELECT i + 1 FROM seq WHERE i < 63
    )
    SELECT '[' || group_concat(v, ',') || ']'
    FROM (
        SELECT CASE
                   WHEN i = 63 THEN '9223372036854775808'
                   ELSE CAST(1 << i AS TEXT)
               END AS v
        FROM seq
        ORDER BY i
    )
)
WHERE amounts IS NULL
   OR trim(amounts) IN ('', '[]');

-- ---------------------------------------------------------------------------
-- 3. Normalize placeholder payment lookup ids.
-- ---------------------------------------------------------------------------
UPDATE mint_quotes
SET checking_id = quote
WHERE checking_id IS NULL
   OR trim(checking_id) = ''
   OR lower(checking_id) IN ('none', 'null');

UPDATE melt_quotes
SET checking_id = quote
WHERE checking_id IS NULL
   OR trim(checking_id) = ''
   OR lower(checking_id) IN ('none', 'null');

-- ---------------------------------------------------------------------------
-- 3b. Deduplicate paid/pending melt quotes per checking_id.
-- ---------------------------------------------------------------------------
WITH ranked AS (
    SELECT quote,
           checking_id,
           row_number() OVER (
               PARTITION BY checking_id
               ORDER BY CASE lower(state) WHEN 'paid' THEN 0
                                          WHEN 'pending' THEN 1
                                          ELSE 2 END,
                        created_time,
                        quote
           ) AS rn
    FROM melt_quotes
    WHERE lower(state) IN ('paid', 'pending')
      AND checking_id IS NOT NULL
      AND trim(checking_id) <> ''
)
UPDATE melt_quotes
SET checking_id = checking_id || '-dup-' || quote
WHERE quote IN (SELECT quote FROM ranked WHERE rn > 1);

-- ---------------------------------------------------------------------------
-- 3c. Deduplicate mint quotes per checking_id (keep the earliest).
-- ---------------------------------------------------------------------------
WITH ranked AS (
    SELECT quote,
           checking_id,
           row_number() OVER (
               PARTITION BY checking_id
               ORDER BY created_time, quote
           ) AS rn
    FROM mint_quotes
    WHERE checking_id IS NOT NULL
      AND trim(checking_id) <> ''
)
UPDATE mint_quotes
SET checking_id = quote
WHERE quote IN (SELECT quote FROM ranked WHERE rn > 1);

-- ---------------------------------------------------------------------------
-- 4. Backfill NULL quote states.
-- ---------------------------------------------------------------------------
UPDATE mint_quotes SET state = 'UNPAID' WHERE state IS NULL;
UPDATE melt_quotes SET state = 'UNPAID' WHERE state IS NULL;

-- ---------------------------------------------------------------------------
-- 5. Prune keysets CDK cannot represent, and their dependent rows.
-- ---------------------------------------------------------------------------
CREATE TEMP TABLE _cdk_pruned_keysets AS
SELECT id
FROM keysets
WHERE NOT (
        (
            (length(id) = 16 AND id NOT GLOB '*[^0-9a-fA-F]*')
            OR (
                length(id) = 66
                AND lower(substr(id, 1, 2)) = '01'
                AND id NOT GLOB '*[^0-9a-fA-F]*'
            )
        )
    AND derivation_path LIKE 'm/%'
    AND NOT (version GLOB '0.[0-9].*' OR version GLOB '0.1[0-4].*')
);

SELECT count(*) AS pruned_keysets FROM _cdk_pruned_keysets;

DELETE FROM promises       WHERE id IN (SELECT id FROM _cdk_pruned_keysets);
DELETE FROM proofs_used    WHERE id IN (SELECT id FROM _cdk_pruned_keysets);
DELETE FROM proofs_pending WHERE id IN (SELECT id FROM _cdk_pruned_keysets);
DELETE FROM keysets        WHERE id IN (SELECT id FROM _cdk_pruned_keysets);

DROP TABLE _cdk_pruned_keysets;

-- ---------------------------------------------------------------------------
-- 6. Remove rows the migrator cannot parse but which still count toward source
--    liabilities (and therefore fail verification).
--    Note: off-curve keys that are valid compressed hex cannot be detected in
--    SQL. If the migrate log reports `invalid B_` for such a row, delete it by
--    its b_ value and re-run.
-- ---------------------------------------------------------------------------
DELETE FROM promises
WHERE c_ IS NOT NULL
  AND (
        b_ IS NULL
     OR length(b_) <> 66
     OR lower(substr(b_, 1, 2)) NOT IN ('02', '03')
     OR b_ GLOB '*[^0-9a-fA-F]*'
     OR length(c_) <> 66
     OR lower(substr(c_, 1, 2)) NOT IN ('02', '03')
     OR c_ GLOB '*[^0-9a-fA-F]*'
  );

-- Pending proofs must carry a real C. Spent proofs with an empty C are allowed
-- via --allow-empty-c, but malformed non-empty C values are not.
DELETE FROM proofs_pending
WHERE c IS NULL
   OR trim(c) = ''
   OR length(c) <> 66
   OR lower(substr(c, 1, 2)) NOT IN ('02', '03')
   OR c GLOB '*[^0-9a-fA-F]*';

DELETE FROM proofs_used
WHERE c IS NOT NULL
  AND trim(c) <> ''
  AND (
        length(c) <> 66
     OR lower(substr(c, 1, 2)) NOT IN ('02', '03')
     OR c GLOB '*[^0-9a-fA-F]*'
  );

-- ---------------------------------------------------------------------------
-- 7. Refresh planner statistics.
-- ---------------------------------------------------------------------------
ANALYZE;

COMMIT;
