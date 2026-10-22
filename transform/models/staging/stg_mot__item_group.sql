-- The test-item hierarchy. Top-level items (e.g. Brakes, Lamps) are the defect categories.
select
    try_cast(test_item_id as integer) || '-' || trim(test_class_id)   as item_group_key,
    try_cast(test_item_id as integer)                                 as test_item_id,
    trim(test_class_id)                                               as test_class_id,
    try_cast(parent_id as integer)                                    as parent_id,
    try_cast(test_item_set_section_id as integer)                     as section_id,
    trim(item_name)                                                   as item_name
from {{ source('raw', 'item_group') }}
