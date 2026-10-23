{#
  A data-quality check on every odometer reading behind the failure rates, adapted from the
  "last-digit test" Montag (2017, Transport Policy) used to look for odometer fraud in
  used-car adverts. A genuine reading's last digit is equally likely to be 0-9, so each
  should be close to 10% of readings. Readings ending in 0, 00 or 000 well above their
  expected share mean some mileages were rounded or estimated rather than read.

  This says something about the data as a whole, never about one car: one car's handful
  of readings is far too few, and rounding is often innocent.
  Grain: one row per pattern checked.
#}
with readings as (
    select test_mileage
    from {{ ref('int_initial_car_tests') }}
    where test_mileage > 0
),

total as (
    select count(*) as total_readings from readings
),

last_digits as (
    select 'last_digit' as check_name,
           (test_mileage % 10)::varchar as pattern,
           count(*) as readings,
           10.0::double as expected_share_pct
    from readings
    group by test_mileage % 10
),

round_endings as (
    select 'ends_with', '00', count(*) filter (where test_mileage % 100 = 0), 1.0::double from readings
    union all
    select 'ends_with', '000', count(*) filter (where test_mileage % 1000 = 0), 0.1::double from readings
)

select
    c.check_name || '-' || c.pattern as check_key,
    c.check_name,
    c.pattern,
    c.readings,
    t.total_readings,
    round(100.0 * c.readings / t.total_readings, 3) as share_pct,
    c.expected_share_pct
from (select * from last_digits union all select * from round_endings) c
cross join total t
