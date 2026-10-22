-- Reconciliation with DVSA's official statistics. Returns a row (= test fails) for any
-- quarter where our test count is more than 1% off, or either failure rate is more than
-- 0.2 percentage points off. DVSA counts classes 3 and 4 together, normal tests only,
-- with results Pass, Fail or PRS.
with ours as (
    select
        p.period_label,
        count(*) as tests,
        100.0 * count(*) filter (where t.is_initial_fail) / count(*) as initial_fail_rate_pct,
        100.0 * count(*) filter (where t.is_final_fail) / count(*)   as final_fail_rate_pct
    from {{ ref('dvsa_published_fail_rates') }} p
    join {{ ref('fct_mot_tests') }} t
      on t.test_date between p.period_start and p.period_end
    where t.test_class_id in ('3', '4')
      and t.test_type = 'NT'
      and t.test_result in ('P', 'F', 'PRS')
    group by p.period_label
)

select
    p.period_label,
    p.tests as dvsa_tests,
    o.tests as our_tests,
    round(100.0 * (o.tests - p.tests) / p.tests, 3) as tests_diff_pct,
    p.initial_fail_rate_pct as dvsa_initial, round(o.initial_fail_rate_pct, 2) as our_initial,
    p.final_fail_rate_pct as dvsa_final, round(o.final_fail_rate_pct, 2) as our_final
from {{ ref('dvsa_published_fail_rates') }} p
left join ours o using (period_label)
where o.tests is null
   or abs(o.tests - p.tests) > 0.01 * p.tests
   or abs(o.initial_fail_rate_pct - p.initial_fail_rate_pct) > 0.2
   or abs(o.final_fail_rate_pct - p.final_fail_rate_pct) > 0.2
