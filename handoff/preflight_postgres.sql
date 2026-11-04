-- Nutshell PostgreSQL preflight (read-only)
-- Usage: psql 'postgres://nutshell:password@host:5432/nutshell' -f preflight_postgres.sql

select 'schema' as check_name, version from dbversions where db = 'mint';

select 'keyset' as row_type, id, version, unit, active, derivation_path,
       input_fee_ppk, final_expiry
from keysets order by valid_from;

select 'counts' as row_type,
       (select count(*) from keysets) as keysets,
       (select count(*) from mint_quotes) as mint_quotes,
       (select count(*) from melt_quotes) as melt_quotes,
       (select count(*) from promises) as promises,
       (select count(*) from proofs_used) as proofs_used,
       (select count(*) from proofs_pending) as proofs_pending;

select 'mint_quote_state' as row_type, state, count(*) as n
from mint_quotes group by state order by state;

select 'melt_quote_state' as row_type, state, count(*) as n
from melt_quotes group by state order by state;

select 'empty_c_used' as row_type, count(*) as n, coalesce(sum(amount),0) as amount
from proofs_used where c is null or c = '';

select 'orphan_promises' as row_type, count(*) as n
from promises where id not in (select id from keysets);

select 'orphan_proofs' as row_type, count(*) as n
from (select id from proofs_used union all select id from proofs_pending) p
where p.id not in (select id from keysets);

select 'duplicate_melt_checking_id' as row_type, checking_id, count(*) as n
from melt_quotes
where lower(state) in ('paid','pending')
group by checking_id having count(*) > 1;

select 'null_c_promises' as row_type, count(*) as n
from promises where c_ is null;

select 'proof_in_both_tables' as row_type, count(*) as n
from proofs_pending p
where exists (select 1 from proofs_used u where u.y = p.y);

-- 0.22+ only; uncomment if the column exists.
-- select 'payment_uncertain' as row_type, count(*) as n
-- from melt_quotes where payment_uncertain = 1;
