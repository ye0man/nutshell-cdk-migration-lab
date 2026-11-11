-- Prepare a *copy* of a Nutshell PostgreSQL database for
-- `cdk-mintd migrate-nutshell`.
--
-- Run this only against a restored/copied database. Never against live
-- production. The migration is offline: stop Nutshell, copy the database,
-- clean the copy, migrate from the copy.
--
-- The migrator normalizes several of these cases while reading, so this file
-- is defense-in-depth: it also keeps the migrator's independent row-count and
-- per-keyset liability checks aligned with the source.
--
-- Idempotent. Review the preview SELECTs before COMMIT if you want to inspect
-- the changes first. The migration target must be empty when you run it.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Preview keysets CDK cannot represent.
--    Kept keysets need a hex id, a BIP32 derivation path, and Nutshell >= 0.15.
-- ---------------------------------------------------------------------------
SELECT id, version, derivation_path, amounts
FROM keysets
WHERE NOT (
        (id ~* '^[0-9a-f]{16}$' OR id ~* '^01[0-9a-f]{64}$')
    AND derivation_path LIKE 'm/%'
    AND version !~ '^0\.([0-9]|1[0-4])(\.|$)'
);

-- ---------------------------------------------------------------------------
-- 2. Repair empty or invalid amount lists.
--    Nutshell keysets span 2^0 .. 2^63. An empty list makes the migrator fall
--    back to a default and serve a keyset whose keys no longer hash to its id.
--    `amounts` is JSON text in upstream Nutshell; if a fork stores jsonb, cast
--    the generated value to jsonb instead.
-- ---------------------------------------------------------------------------
UPDATE keysets
SET amounts = (
    SELECT '[' || string_agg((power(2::numeric, i))::text, ',' ORDER BY i) || ']'
    FROM generate_series(0, 63) AS s(i)
)
WHERE (amounts IS NULL OR btrim(amounts) IN ('', '[]'))
  AND (id ~* '^[0-9a-f]{16}$' OR id ~* '^01[0-9a-f]{64}$');

-- ---------------------------------------------------------------------------
-- 3. Normalize placeholder payment lookup ids.
--    Older rows use NULL or the literal "None"; CDK requires a unique
--    request_lookup_id.
-- ---------------------------------------------------------------------------
UPDATE mint_quotes
SET checking_id = quote
WHERE checking_id IS NULL
   OR btrim(checking_id) = ''
   OR lower(checking_id) IN ('none', 'null');

UPDATE melt_quotes
SET checking_id = quote
WHERE checking_id IS NULL
   OR btrim(checking_id) = ''
   OR lower(checking_id) IN ('none', 'null');

-- ---------------------------------------------------------------------------
-- 3b. Deduplicate paid/pending melt quotes per checking_id.
--     Keep PAID first, then the earliest; rename the rest with -dup-<quote>.
-- ---------------------------------------------------------------------------
WITH ranked AS (
    SELECT quote,
           checking_id,
           row_number() OVER (
               PARTITION BY checking_id
               ORDER BY CASE lower(state) WHEN 'paid' THEN 0
                                          WHEN 'pending' THEN 1
                                          ELSE 2 END,
                        created_time NULLS LAST,
                        quote
           ) AS rn
    FROM melt_quotes
    WHERE lower(state) IN ('paid', 'pending')
      AND checking_id IS NOT NULL
      AND btrim(checking_id) <> ''
)
UPDATE melt_quotes m
SET checking_id = m.checking_id || '-dup-' || m.quote
FROM ranked r
WHERE m.quote = r.quote
  AND r.rn > 1;

-- ---------------------------------------------------------------------------
-- 3c. Deduplicate mint quotes per checking_id (keep the earliest).
-- ---------------------------------------------------------------------------
WITH ranked AS (
    SELECT quote,
           checking_id,
           row_number() OVER (
               PARTITION BY checking_id
               ORDER BY created_time NULLS LAST, quote
           ) AS rn
    FROM mint_quotes
    WHERE checking_id IS NOT NULL
      AND btrim(checking_id) <> ''
)
UPDATE mint_quotes m
SET checking_id = m.quote
FROM ranked r
WHERE m.quote = r.quote
  AND r.rn > 1;

-- ---------------------------------------------------------------------------
-- 4. Backfill NULL quote states. NULL means unpaid.
-- ---------------------------------------------------------------------------
UPDATE mint_quotes SET state = 'UNPAID' WHERE state IS NULL;
UPDATE melt_quotes SET state = 'UNPAID' WHERE state IS NULL;

-- ---------------------------------------------------------------------------
-- 4b. Clamp out-of-range (Y2038) melt-quote expiry.
--     CDK stores expiry as int4 (ceiling 2038-01-19). Historical settled melts
--     do not need a meaningful expiry, so fall back to created_time.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    expiry_type text;
BEGIN
    SELECT data_type INTO expiry_type
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'melt_quotes'
      AND column_name = 'expiry';

    IF expiry_type IN ('character varying', 'text', 'character') THEN
        UPDATE melt_quotes
        SET expiry = created_time::text
        WHERE expiry ~ '^[0-9]+$'
          AND expiry::bigint > 2147483647;
    ELSIF expiry_type IN ('integer', 'bigint', 'smallint', 'numeric') THEN
        UPDATE melt_quotes
        SET expiry = created_time
        WHERE expiry > 2147483647;
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 5. Prune keysets CDK cannot represent, and their dependent rows.
--    Leaving their liabilities behind makes per-keyset verification fail.
-- ---------------------------------------------------------------------------
CREATE TEMP TABLE _cdk_pruned_keysets ON COMMIT DROP AS
SELECT id
FROM keysets
WHERE NOT (
        (id ~* '^[0-9a-f]{16}$' OR id ~* '^01[0-9a-f]{64}$')
    AND derivation_path LIKE 'm/%'
    AND version !~ '^0\.([0-9]|1[0-4])(\.|$)'
);

SELECT count(*) AS pruned_keysets FROM _cdk_pruned_keysets;

DELETE FROM promises       WHERE id IN (SELECT id FROM _cdk_pruned_keysets);
DELETE FROM proofs_used    WHERE id IN (SELECT id FROM _cdk_pruned_keysets);
DELETE FROM proofs_pending WHERE id IN (SELECT id FROM _cdk_pruned_keysets);

DO $$
BEGIN
    IF to_regclass('public.mint_pubkeys') IS NOT NULL THEN
        DELETE FROM mint_pubkeys WHERE id IN (SELECT id FROM _cdk_pruned_keysets);
    END IF;
    IF to_regclass('public.pubkeys') IS NOT NULL THEN
        DELETE FROM pubkeys WHERE id IN (SELECT id FROM _cdk_pruned_keysets);
    END IF;
END $$;

DELETE FROM keysets WHERE id IN (SELECT id FROM _cdk_pruned_keysets);

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
     OR b_ !~* '^0[23][0-9a-f]{64}$'
     OR c_ !~* '^0[23][0-9a-f]{64}$'
  );

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'promises' AND column_name = 'dleq_e'
    ) AND EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'promises' AND column_name = 'dleq_s'
    ) THEN
        DELETE FROM promises
        WHERE (dleq_e IS NOT NULL AND dleq_e !~* '^[0-9a-f]{64}$')
           OR (dleq_s IS NOT NULL AND dleq_s !~* '^[0-9a-f]{64}$');
    END IF;
END $$;

-- Pending proofs must carry a real C. Spent proofs with an empty C are allowed
-- via --allow-empty-c, but malformed non-empty C values are not.
DELETE FROM proofs_pending
WHERE c IS NULL
   OR btrim(c) = ''
   OR c !~* '^0[23][0-9a-f]{64}$';

DELETE FROM proofs_used
WHERE c IS NOT NULL
  AND btrim(c) <> ''
  AND c !~* '^0[23][0-9a-f]{64}$';

-- ---------------------------------------------------------------------------
-- 7. Refresh planner statistics for the chunked ORDER BY .. OFFSET reads.
-- ---------------------------------------------------------------------------
ANALYZE;

COMMIT;
