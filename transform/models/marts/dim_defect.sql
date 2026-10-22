-- One row per defect (RfR) per vehicle class, with its top-level category from the
-- DVSA test-item hierarchy (e.g. Brakes, Lamps, Tyres).
select
    d.defect_key,
    d.rfr_id,
    d.test_class_id,
    d.description,
    d.advisory_text,
    d.deficiency_category,
    d.section_id,
    coalesce(g.item_name, 'Unknown') as defect_category
from {{ ref('stg_mot__item_detail') }} d
left join {{ ref('stg_mot__item_group') }} g
    on g.test_item_id = d.section_id
   and g.test_class_id = d.test_class_id
