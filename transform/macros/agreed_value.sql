{#
  Cleaning rule 3: when the copies of one test disagree about a column, we don't guess.
  Used inside GROUP BY test_id:
    agreed_value(col)  -> the value if every copy has the same value (or every copy is blank),
                          otherwise NULL
    disagrees(col)     -> true when the copies disagree
  min/max/count is used instead of count(DISTINCT ...) because it is far cheaper on tens of
  millions of groups.
#}
{% macro _agrees(col) -%}
    (min({{ col }}) IS NOT DISTINCT FROM max({{ col }}) AND count({{ col }}) IN (0, count(*)))
{%- endmacro %}

{% macro agreed_value(col) -%}
    CASE WHEN {{ _agrees(col) }} THEN min({{ col }}) END
{%- endmacro %}

{% macro disagrees(col) -%}
    (NOT {{ _agrees(col) }})
{%- endmacro %}
