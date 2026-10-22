-- One row per published line of the results files, typed. Copies are still here;
-- they are resolved in int_test_results_deduped.
with source as (
    select * from {{ source('raw', 'test_result') }}
    where test_id <> 'test_id'          -- cleaning rule 1: repeated header lines
)

select
    try_cast(test_id as bigint)                           as test_id,
    try_cast(vehicle_id as bigint)                        as vehicle_id,
    try_cast(test_date as date)                           as test_date,
    nullif(trim(test_class_id), '')                       as test_class_id,
    nullif(trim(test_type), '')                           as test_type,
    nullif(trim(test_result), '')                         as test_result,
    -- published as "71614.0"; blank means no reading was taken
    try_cast(try_cast(test_mileage as double) as bigint)  as test_mileage,
    nullif(trim(postcode_area), '')                       as postcode_area,
    nullif(trim(make), '')                                as make,
    nullif(trim(model), '')                               as model,
    nullif(trim(colour), '')                              as colour,
    nullif(trim(fuel_type), '')                           as fuel_type,
    try_cast(cylinder_capacity as integer)                as cylinder_capacity,
    -- DVLA uses 1971-01-01 when the real date is unknown (DVSA user guide)
    case when first_use_date = '1971-01-01' then null
         else try_cast(first_use_date as date) end        as first_use_date,
    try_cast(replace(completed_date, 'Z', '') as timestamp) as completed_at,
    source_file
from source
