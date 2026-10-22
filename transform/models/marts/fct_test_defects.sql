-- Grain: one row per distinct defect recorded on a test.
-- Cleaning rule 4: an exact repeat of the same defect line on the same test is kept once.
with distinct_items as (
    select distinct test_id, rfr_id, rfr_type_code, location_id, is_dangerous_mark
    from {{ ref('stg_mot__test_items') }}
)

select
    -- md5_number stores the key as a 16-byte number rather than 32 characters of text:
    -- this table has ~90 million rows, so that saves a lot of disk
    md5_number(concat_ws('|', i.test_id, i.rfr_id, i.rfr_type_code,
                         coalesce(i.location_id, -1), i.is_dangerous_mark)) as test_defect_key,
    i.test_id,
    d.defect_key,                       -- NULL when DVSA's lookup has no entry for this defect
    i.rfr_id,
    i.rfr_type_code,
    i.location_id,
    i.is_dangerous_mark,
    t.test_class_id
from distinct_items i
join {{ ref('fct_mot_tests') }} t on t.test_id = i.test_id
left join {{ ref('dim_defect') }} d
    on d.rfr_id = i.rfr_id
   and d.test_class_id = t.test_class_id
