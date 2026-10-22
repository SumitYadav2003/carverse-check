-- Grain: one row per make + model + year of first use, for groups with enough tests.
-- Each group is compared with all cars first used in the same year (its "peers"),
-- because age is the biggest driver of MOT failure.
with base as (
    select * from {{ ref('int_initial_car_tests') }}
),

peers as (
    select
        first_use_year,
        count(*) as peer_tests,
        100.0 * avg(is_initial_fail::int) as peer_initial_fail_rate_pct,
        100.0 * avg(is_final_fail::int)   as peer_final_fail_rate_pct
    from base
    group by first_use_year
),

groups as (
    select
        vehicle_model_key,
        make,
        model,
        first_use_year,
        count(*) as tests,
        100.0 * avg(is_initial_fail::int) as initial_fail_rate_pct,
        100.0 * avg(is_final_fail::int)   as final_fail_rate_pct,
        median(test_mileage)              as median_mileage
    from base
    where vehicle_model_key is not null
    group by vehicle_model_key, make, model, first_use_year
    having count(*) >= {{ var('min_tests_per_group') }}
)

select
    g.vehicle_model_key || '-' || g.first_use_year as model_year_key,
    g.vehicle_model_key,
    g.make,
    g.model,
    g.first_use_year,
    g.tests,
    round(g.initial_fail_rate_pct, 2) as initial_fail_rate_pct,
    round(g.final_fail_rate_pct, 2)   as final_fail_rate_pct,
    g.median_mileage::bigint          as median_mileage,
    p.peer_tests,
    round(p.peer_initial_fail_rate_pct, 2) as peer_initial_fail_rate_pct,
    round(p.peer_final_fail_rate_pct, 2)   as peer_final_fail_rate_pct,
    round(g.initial_fail_rate_pct - p.peer_initial_fail_rate_pct, 2) as initial_fail_rate_vs_peers_pts
from groups g
join peers p using (first_use_year)
