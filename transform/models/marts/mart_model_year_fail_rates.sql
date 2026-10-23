{#
  Grain: one row per make + model + year of first use, for groups with enough tests.
  Each group is compared with all cars first used in the same year (its "peers"), because
  age is the biggest driver of MOT failure.

  Raw rates from small groups are noisy: 12 failures in 30 tests is 40%, but the true rate
  could easily be 25% or 58%. So every group also gets:
    - a 95% range for its raw rate (Wilson score interval)
    - an adjusted estimate (empirical Bayes, a beta-binomial model): the raw rate pulled
      towards the peer rate, strongly for small groups and hardly at all for big ones,
      with its own 95% range
    - vs_peers, the verdict a buyer sees: 'higher' or 'lower' only when the adjusted
      estimate's whole range is on one side of the peer rate AND the gap is at least
      var('min_meaningful_difference_pts'); otherwise 'within'
    - funnel limits (Spiegelhalter, 2005) and funnel_position: whether the model stands
      out from other models of the same age, allowing for chance AND the normal
      differences between models. A different question from vs_peers: a big, popular model
      can be clearly worse than average yet still within the normal spread of models.
#}
with groups as (
    select * from {{ ref('int_model_year_groups') }}
),

peers as (
    select * from {{ ref('int_peer_year_spread') }}
),

joined as (
    select
        g.*,
        p.peer_tests,
        p.peer_initial_fail_rate as target,
        p.peer_final_fail_rate,
        p.between_model_variance as tau2,
        g.initial_fails::double / g.tests as rate,
        p.peer_initial_fail_rate * (1 - p.peer_initial_fail_rate) / g.tests as chance_variance,
        -- Beta prior centred on the peer rate with variance tau2; M is its weight in
        -- "pseudo-tests". tau2 = 0 means models don't differ beyond chance: full pull.
        case when p.between_model_variance > 0
             then p.peer_initial_fail_rate * (1 - p.peer_initial_fail_rate)
                  / p.between_model_variance - 1
        end as prior_weight
    from groups g
    join peers p using (first_use_year)
),

stats as (
    select
        *,
        -- weight of the prior in "pseudo-tests": 0 if the spread is too wide to pull
        -- towards anything; tau2 = 0 (models don't differ beyond chance) means full pull
        case when tau2 > 0 then greatest(prior_weight, 0) end as m,
        target - 1.959964 * sqrt(chance_variance + tau2) as funnel_low_95,
        target + 1.959964 * sqrt(chance_variance + tau2) as funnel_high_95,
        target - 3.090232 * sqrt(chance_variance + tau2) as funnel_low_998,
        target + 3.090232 * sqrt(chance_variance + tau2) as funnel_high_998
    from joined
),

estimates as (
    -- Posterior Beta(fails + target*m, passes + (1-target)*m): its mean is the adjusted
    -- rate; its 95% range uses the normal approximation, fine for 30+ tests.
    select
        *,
        case when m is null then target
             else (initial_fails + target * m) / (tests + m) end as estimated_rate,
        case when m is null then 0
             else 1.959964 * sqrt(
                 ((initial_fails + target * m) / (tests + m))
                 * (1 - (initial_fails + target * m) / (tests + m))
                 / (tests + m + 1)) end as estimate_margin
    from stats
)

select
    vehicle_model_key || '-' || first_use_year as model_year_key,
    vehicle_model_key,
    make,
    model,
    first_use_year,
    tests,
    initial_fails,
    round(100 * rate, 2)                                                   as initial_fail_rate_pct,
    round(100.0 * final_fails / tests, 2)                                  as final_fail_rate_pct,
    round(100 * {{ wilson_bound('initial_fails', 'tests', 'low') }}, 2)    as initial_fail_rate_low_pct,
    round(100 * {{ wilson_bound('initial_fails', 'tests', 'high') }}, 2)   as initial_fail_rate_high_pct,
    round(100 * estimated_rate, 2)                                         as estimated_initial_fail_rate_pct,
    round(100 * greatest(0, estimated_rate - estimate_margin), 2)          as estimated_low_pct,
    round(100 * least(1, estimated_rate + estimate_margin), 2)             as estimated_high_pct,
    median_mileage::bigint                                                 as median_mileage,
    mileage_readings,
    miles_per_year_p10::bigint as miles_per_year_p10,
    miles_per_year_p25::bigint as miles_per_year_p25,
    miles_per_year_p50::bigint as miles_per_year_p50,
    miles_per_year_p75::bigint as miles_per_year_p75,
    miles_per_year_p90::bigint as miles_per_year_p90,
    peer_tests,
    round(100 * target, 2)                                                 as peer_initial_fail_rate_pct,
    round(100 * peer_final_fail_rate, 2)                                   as peer_final_fail_rate_pct,
    round(100 * (rate - target), 2)                                        as initial_fail_rate_vs_peers_pts,
    round(100 * sqrt(tau2), 4)                                             as peer_between_model_sd_pts,
    round(100 * greatest(0, funnel_low_95), 2)                             as funnel_low_95_pct,
    round(100 * least(1, funnel_high_95), 2)                               as funnel_high_95_pct,
    round(100 * greatest(0, funnel_low_998), 2)                            as funnel_low_998_pct,
    round(100 * least(1, funnel_high_998), 2)                              as funnel_high_998_pct,
    case when estimated_rate - estimate_margin > target
          and 100 * (estimated_rate - target) >= {{ var('min_meaningful_difference_pts') }} then 'higher'
         when estimated_rate + estimate_margin < target
          and 100 * (target - estimated_rate) >= {{ var('min_meaningful_difference_pts') }} then 'lower'
         else 'within' end                                                 as vs_peers,
    case when rate > funnel_high_95 then 'above'
         when rate < funnel_low_95  then 'below'
         else 'inside' end                                                 as funnel_position
from estimates
