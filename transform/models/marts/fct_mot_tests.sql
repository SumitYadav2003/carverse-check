-- Grain: one row per MOT test.
select
    t.test_id,
    t.vehicle_id,
    t.test_date,
    t.completed_at,
    t.test_class_id,
    t.test_type,
    t.test_result,
    t.test_mileage,
    m.vehicle_model_key,
    t.fuel_type,
    t.cylinder_capacity,
    t.first_use_year,
    year(t.test_date) - t.first_use_year as vehicle_age_years,
    t.postcode_area,
    -- DVSA's definitions: a PRS result started the test in a failing state
    t.test_result in ('F', 'PRS') as is_initial_fail,
    t.test_result = 'F' as is_final_fail,
    t.published_copies,
    t.has_conflicting_copies
from {{ ref('int_test_results_deduped') }} t
left join {{ ref('dim_vehicle_model') }} m
    on m.make = t.make and m.model = t.model
