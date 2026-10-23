{{ config(materialized='view') }}
-- The tests DVSA's failure rates are built on: cars and light vans (class 4), normal
-- (initial) tests, with result Pass, Fail or PRS. Retests, abandoned and aborted tests are
-- excluded, as in DVSA's published statistics.
select
    t.test_id,
    t.vehicle_model_key,
    m.make,
    m.model,
    t.test_date,
    t.first_use_date,
    t.first_use_year,
    t.vehicle_age_years,
    t.test_mileage,
    -- Average miles a year since the car was first used. Only when the reading is real
    -- (above 0), the exact first-use date is known (copies agreed on it) and the car is
    -- at least 2.5 years old: a first MOT is due at 3 years, so anything younger is odd.
    case
        when t.test_mileage > 0
         and t.first_use_date is not null
         and date_diff('day', t.first_use_date, t.test_date) >= 913
        then t.test_mileage / (date_diff('day', t.first_use_date, t.test_date) / 365.25)
    end as miles_per_year,
    t.is_initial_fail,
    t.is_final_fail
from {{ ref('fct_mot_tests') }} t
left join {{ ref('dim_vehicle_model') }} m using (vehicle_model_key)
where t.test_class_id = '4'
  and t.test_type = 'NT'
  and t.test_result in ('P', 'F', 'PRS')
  and t.first_use_year is not null
