{#
  One end of the Wilson score interval (Wilson, 1927) for a proportion: the range the true
  rate probably lies in, given `successes` out of `n`. Unlike "rate +/- 1.96 x standard
  error" it never goes below 0% or above 100%, and it behaves well for small groups.
  side: 'low' or 'high'. Returns a fraction (0-1), not a percentage.
#}
{% macro wilson_bound(successes, n, side, z=1.959964) %}
    (
        ({{ successes }})::double / ({{ n }}) + pow({{ z }}, 2) / (2.0 * ({{ n }}))
        {{ '-' if side == 'low' else '+' }}
        {{ z }} * sqrt(
            ({{ successes }})::double / ({{ n }}) * (1 - ({{ successes }})::double / ({{ n }})) / ({{ n }})
            + pow({{ z }}, 2) / (4.0 * pow({{ n }}, 2))
        )
    ) / (1 + pow({{ z }}, 2) / ({{ n }}))
{% endmacro %}
