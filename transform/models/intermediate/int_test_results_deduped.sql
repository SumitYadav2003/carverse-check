{#
  One row per test. Applies cleaning rules 2 and 3:
    rule 2  exact copies of a test collapse into one row (GROUP BY test_id)
    rule 3  where copies disagree about a column, that column is set to NULL rather than
            guessed, and the test is flagged
  Because only the year of first use is needed downstream, the year is kept whenever
  the copies agree on it, even if they disagree about the exact day.
#}
{% set cols = ['vehicle_id', 'test_date', 'test_class_id', 'test_type', 'test_result',
               'test_mileage', 'postcode_area', 'make', 'model', 'colour', 'fuel_type',
               'cylinder_capacity', 'first_use_date', 'completed_at'] %}

select
    test_id,
    {% for c in cols %}
    {{ agreed_value(c) }} as {{ c }},
    {% endfor %}
    {{ agreed_value('year(first_use_date)') }} as first_use_year,
    count(*) as published_copies,
    (
        {% for c in cols %}{{ disagrees(c) }}{% if not loop.last %} or {% endif %}{% endfor %}
    ) as has_conflicting_copies
from {{ ref('stg_mot__test_results') }}
group by test_id
