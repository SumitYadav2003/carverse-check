-- Fails for any mart row with an impossible value. Each condition is a rule that must hold
-- by construction, so a row here means a bug, not an interesting finding.
-- (0.01 allows for rounding to 2 decimal places.)
select 'fail_rates' as mart, model_year_key as key
from {{ ref('mart_model_year_fail_rates') }}
where initial_fail_rate_pct not between 0 and 100
   or final_fail_rate_pct not between 0 and 100
   -- a PRS result is an initial failure that was fixed, so final can never exceed initial
   or final_fail_rate_pct > initial_fail_rate_pct
   or tests < {{ var('min_tests_per_group') }}
   -- the 95% range must contain the rate itself
   or initial_fail_rate_pct < initial_fail_rate_low_pct - 0.01
   or initial_fail_rate_pct > initial_fail_rate_high_pct + 0.01
   -- the adjusted estimate always lies between the group's own rate and the peer rate
   or estimated_initial_fail_rate_pct < least(initial_fail_rate_pct, peer_initial_fail_rate_pct) - 0.01
   or estimated_initial_fail_rate_pct > greatest(initial_fail_rate_pct, peer_initial_fail_rate_pct) + 0.01
   -- funnel limits sit around the peer rate, the 99.8% ones outside the 95% ones
   or peer_initial_fail_rate_pct not between funnel_low_95_pct - 0.01 and funnel_high_95_pct + 0.01
   or funnel_low_998_pct > funnel_low_95_pct
   or funnel_high_998_pct < funnel_high_95_pct
   -- the adjusted estimate sits inside its own range
   or estimated_initial_fail_rate_pct not between estimated_low_pct - 0.01 and estimated_high_pct + 0.01
   -- the verdict must agree with the estimate's range and the minimum gap
   or (vs_peers = 'higher' and (estimated_low_pct < peer_initial_fail_rate_pct - 0.01
        or estimated_initial_fail_rate_pct - peer_initial_fail_rate_pct < {{ var('min_meaningful_difference_pts') }} - 0.02))
   or (vs_peers = 'lower' and (estimated_high_pct > peer_initial_fail_rate_pct + 0.01
        or peer_initial_fail_rate_pct - estimated_initial_fail_rate_pct < {{ var('min_meaningful_difference_pts') }} - 0.02))
   -- and the funnel position must agree with the funnel limits
   or (funnel_position = 'above' and initial_fail_rate_pct < funnel_high_95_pct - 0.01)
   or (funnel_position = 'below' and initial_fail_rate_pct > funnel_low_95_pct + 0.01)
   -- mileage percentiles must be in order
   or miles_per_year_p10 > miles_per_year_p25
   or miles_per_year_p25 > miles_per_year_p50
   or miles_per_year_p50 > miles_per_year_p75
   or miles_per_year_p75 > miles_per_year_p90

union all

select 'defect_categories', model_year_category_key
from {{ ref('mart_model_year_defect_categories') }}
where failure_share_pct not between 0 and 100
   or advisory_share_pct not between 0 and 100
   or peer_failure_share_pct not between 0 and 100
   or failure_share_low_pct > failure_share_pct + 0.01
   or tests < {{ var('min_tests_for_categories') }}

union all

-- the ten last digits must account for every reading
select 'odometer_rounding', 'last digits'
from {{ ref('mart_odometer_rounding') }}
where check_name = 'last_digit'
having count(*) <> 10 or sum(readings) <> max(total_readings)
