-- Grain: one row per make + model + year of first use + defect category.
-- Follows DVSA's method for "initial failures by defect category": a test counts towards a
-- category if it had at least one Fail or PRS item in that category. Advisories are
-- counted the same way, separately.
-- Only groups with at least var('min_tests_for_categories') tests: a category is a small
-- slice of a group, so it needs more tests than the overall rate before it means anything.
with base as (
    select * from {{ ref('int_initial_car_tests') }}
),

test_categories as (
    -- one row per test per category it had any item in
    select
        d.test_id,
        dd.defect_category,
        bool_or(d.rfr_type_code in ('F', 'P')) as had_failure_item,
        bool_or(d.rfr_type_code = 'A')         as had_advisory
    from {{ ref('fct_test_defects') }} d
    join {{ ref('dim_defect') }} dd using (defect_key)
    semi join base b on b.test_id = d.test_id
    group by d.test_id, dd.defect_category
),

with_test as (
    select tc.*, b.vehicle_model_key, b.first_use_year
    from test_categories tc
    join base b using (test_id)
),

peer_tests as (
    select first_use_year, count(*) as peer_tests from base group by first_use_year
),

peers as (
    select
        w.first_use_year,
        w.defect_category,
        100.0 * count(*) filter (where had_failure_item) / max(p.peer_tests) as peer_failure_share_pct,
        100.0 * count(*) filter (where had_advisory) / max(p.peer_tests)     as peer_advisory_share_pct
    from with_test w
    join peer_tests p using (first_use_year)
    group by w.first_use_year, w.defect_category
),

groups as (
    select
        m.model_year_key,
        w.defect_category,
        count(*) filter (where had_failure_item) as tests_with_failure_item,
        count(*) filter (where had_advisory)     as tests_with_advisory
    from with_test w
    join {{ ref('mart_model_year_fail_rates') }} m
      on m.vehicle_model_key = w.vehicle_model_key
     and m.first_use_year = w.first_use_year
    where m.tests >= {{ var('min_tests_for_categories') }}
    group by m.model_year_key, w.defect_category
)

select
    g.model_year_key || '-' || g.defect_category as model_year_category_key,
    g.model_year_key,
    m.make,
    m.model,
    m.first_use_year,
    g.defect_category,
    m.tests,
    g.tests_with_failure_item,
    g.tests_with_advisory,
    round(100.0 * g.tests_with_failure_item / m.tests, 2) as failure_share_pct,
    -- bottom of the 95% range: a category is only called "above average" if even this
    -- is above the peer share
    round(100 * {{ wilson_bound('g.tests_with_failure_item', 'm.tests', 'low') }}, 2) as failure_share_low_pct,
    round(100.0 * g.tests_with_advisory / m.tests, 2)     as advisory_share_pct,
    round(p.peer_failure_share_pct, 2)  as peer_failure_share_pct,
    round(p.peer_advisory_share_pct, 2) as peer_advisory_share_pct
from groups g
join {{ ref('mart_model_year_fail_rates') }} m using (model_year_key)
join peers p
  on p.first_use_year = m.first_use_year
 and p.defect_category = g.defect_category
