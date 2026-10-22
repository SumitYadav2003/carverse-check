-- What each defect (RfR) means, per vehicle class.
select
    try_cast(rfr_id as integer) || '-' || trim(test_class_id)   as defect_key,
    try_cast(rfr_id as integer)                                 as rfr_id,
    trim(test_class_id)                                         as test_class_id,
    try_cast(test_item_id as integer)                           as test_item_id,
    try_cast(test_item_set_section_id as integer)               as section_id,
    trim(rfr_deficiency_category)                               as deficiency_category,
    trim(rfr_desc)                                              as description,
    nullif(trim(rfr_advisory_text), '')                         as advisory_text
from {{ source('raw', 'item_detail') }}
