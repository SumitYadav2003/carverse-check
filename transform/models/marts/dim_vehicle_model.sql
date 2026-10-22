-- One row per make and model.
select distinct
    md5(make || '|' || model) as vehicle_model_key,
    make,
    model
from {{ ref('int_test_results_deduped') }}
where make is not null
  and model is not null
  and upper(make) <> 'UNCLASSIFIED'     -- DVSA had no valid vehicle record
