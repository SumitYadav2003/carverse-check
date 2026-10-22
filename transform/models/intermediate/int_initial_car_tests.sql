{{ config(materialized='view') }}
-- The tests DVSA's failure rates are built on: cars and light vans (class 4), normal
-- (initial) tests, with result Pass, Fail or PRS. Retests, abandoned and aborted tests are
-- excluded, as in DVSA's published statistics.
select
    t.test_id,
    t.vehicle_model_key,
    m.make,
    m.model,
    t.first_use_year,
    t.vehicle_age_years,
    t.test_mileage,
    t.is_initial_fail,
    t.is_final_fail
from {{ ref('fct_mot_tests') }} t
left join {{ ref('dim_vehicle_model') }} m using (vehicle_model_key)
where t.test_class_id = '4'
  and t.test_type = 'NT'
  and t.test_result in ('P', 'F', 'PRS')
  and t.first_use_year is not null
