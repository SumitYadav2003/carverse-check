{#
  Grain: one row per year of first use ("peers": all cars of the same age).

  Two numbers per year:
    peer_initial_fail_rate   the failure rate of all cars first used that year (the target)
    between_model_variance   how much models of that age genuinely differ from each other,
                             beyond what chance alone would produce (tau squared)

  Method: Spiegelhalter (2005), "Handling over-dispersion of performance indicators",
  additive random-effects version, the approach used for funnel plots of hospitals.
    1. z-score each model group against the target: z = (rate - target) / s,
       where s = sqrt(target * (1 - target) / tests) is the spread chance alone would give.
    2. Winsorise: clip z to its var('spread_clip_quantile') and 1 - that percentiles, so a
       few extreme groups don't inflate the estimate. Spiegelhalter clips at 10%/90%; we
       use 1%/99% because simulation showed 10% halves the estimate when every model
       genuinely differs (see pipeline/check_spread_estimator.py).
    3. phi = mean of the clipped z squared. If models only differed by chance, phi ~ 1.
    4. tau^2 = (I * phi - (I - 1)) / (sum(w) - sum(w^2) / sum(w)), w = 1 / s^2, I = groups;
       0 if negative.
  Years with fewer than var('min_groups_for_spread') groups get 0 (chance alone).
#}
with peers as (
    select
        first_use_year,
        count(*)                          as peer_tests,
        avg(is_initial_fail::int)         as peer_initial_fail_rate,
        avg(is_final_fail::int)           as peer_final_fail_rate
    from {{ ref('int_initial_car_tests') }}
    group by first_use_year
),

scored as (
    select
        g.first_use_year,
        (g.initial_fails::double / g.tests - p.peer_initial_fail_rate)
            / sqrt(p.peer_initial_fail_rate * (1 - p.peer_initial_fail_rate) / g.tests) as z,
        g.tests / (p.peer_initial_fail_rate * (1 - p.peer_initial_fail_rate))           as w
    from {{ ref('int_model_year_groups') }} g
    join peers p using (first_use_year)
    -- a target of exactly 0% or 100% has no spread to measure against
    where p.peer_initial_fail_rate > 0 and p.peer_initial_fail_rate < 1
),

clip as (
    select first_use_year,
           quantile_cont(z, {{ var('spread_clip_quantile') }})     as z_low,
           quantile_cont(z, 1 - {{ var('spread_clip_quantile') }}) as z_high
    from scored
    group by first_use_year
),

spread as (
    select
        s.first_use_year,
        count(*)                                                as model_groups,
        avg(pow(least(greatest(s.z, c.z_low), c.z_high), 2))     as overdispersion_ratio,
        sum(s.w)                                                as sum_w,
        sum(pow(s.w, 2))                                        as sum_w2
    from scored s
    join clip c using (first_use_year)
    group by s.first_use_year
)

select
    p.first_use_year,
    p.peer_tests,
    p.peer_initial_fail_rate,
    p.peer_final_fail_rate,
    coalesce(s.model_groups, 0) as model_groups,
    round(s.overdispersion_ratio, 4) as overdispersion_ratio,
    case
        when coalesce(s.model_groups, 0) < {{ var('min_groups_for_spread') }} then 0
        else round(greatest(0,
            (s.model_groups * s.overdispersion_ratio - (s.model_groups - 1))
            / (s.sum_w - s.sum_w2 / s.sum_w)), 10)
    end as between_model_variance
from peers p
left join spread s using (first_use_year)
