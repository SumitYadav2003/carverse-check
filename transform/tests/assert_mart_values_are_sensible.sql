-- Fails for any mart row with an impossible value: a percentage outside 0-100, a final
-- failure rate above the initial one (a PRS result is an initial failure that was fixed,
-- so final can never exceed initial), or a group below the minimum size.
select 'fail_rates' as mart, model_year_key as key
from {{ ref('mart_model_year_fail_rates') }}
where initial_fail_rate_pct not between 0 and 100
   or final_fail_rate_pct not between 0 and 100
   or final_fail_rate_pct > initial_fail_rate_pct
   or tests < {{ var('min_tests_per_group') }}

union all

select 'defect_categories', model_year_category_key
from {{ ref('mart_model_year_defect_categories') }}
where failure_share_pct not between 0 and 100
   or advisory_share_pct not between 0 and 100
   or peer_failure_share_pct not between 0 and 100
