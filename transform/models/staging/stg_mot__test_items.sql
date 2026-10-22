-- One row per published line of the failure-item files, typed. Copies are still here;
-- they are removed in fct_test_defects.
select
    try_cast(test_id as bigint)                          as test_id,
    try_cast(rfr_id as integer)                          as rfr_id,
    nullif(trim(rfr_type_code), '')                      as rfr_type_code,
    try_cast(mot_test_rfr_location_type_id as integer)   as location_id,
    coalesce(trim(dangerous_mark) = 'D', false)          as is_dangerous_mark,
    source_file
from {{ source('raw', 'test_item') }}
where test_id <> 'test_id'              -- cleaning rule 1: repeated header lines
