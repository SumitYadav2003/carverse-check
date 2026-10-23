-- Grain: one row per make + model + year of first use with enough tests to publish.
-- Counts only; the statistics are added in int_peer_year_spread and the mart.
select
    vehicle_model_key,
    make,
    model,
    first_use_year,
    count(*)                                   as tests,
    count(*) filter (where is_initial_fail)    as initial_fails,
    count(*) filter (where is_final_fail)      as final_fails,
    median(test_mileage)                       as median_mileage,
    -- how far cars of this model and age are driven each year, as a spread, so one car
    -- can be placed within it
    count(miles_per_year)                      as mileage_readings,
    quantile_cont(miles_per_year, 0.10)        as miles_per_year_p10,
    quantile_cont(miles_per_year, 0.25)        as miles_per_year_p25,
    quantile_cont(miles_per_year, 0.50)        as miles_per_year_p50,
    quantile_cont(miles_per_year, 0.75)        as miles_per_year_p75,
    quantile_cont(miles_per_year, 0.90)        as miles_per_year_p90
from {{ ref('int_initial_car_tests') }}
where vehicle_model_key is not null
group by vehicle_model_key, make, model, first_use_year
having count(*) >= {{ var('min_tests_per_group') }}
