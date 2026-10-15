# Observation-driven recommendation: implementation contract

This revision supersedes the hard-assignment runtime plan. Preserve GIS, 11
stations, physical FIFO, legacy ideal PDHG/GKPS/repair benchmarks. GAMA is runtime;
Python is independent validation only. Robot integration remains NOT_IMPLEMENTED.

Implementation and functional verification of this pipeline are complete. See
[RECOMMENDATION_VALIDATION.md](RECOMMENDATION_VALIDATION.md) for PASS evidence,
negative forecast/correction results, solver timeouts and the research experiment
coverage that remains unverified. Functional gate completion is not an efficacy
claim for B4/B4-N or a completed empirical city-scale study.

## Ordered gates

0. Record baseline compile/tests and input fingerprints.
1. Lock Pareto + minimax reference and discrete physical waiting reference.
2. Separate recommendation, EVChoice, optional intention and actual arrival.
3. B3: read-only station-local physical waiting at ETA; LIVE/LIMITED metadata.
4. B4: causal closed-bin arrivals, moving average, discrete historical replay.
5. B4-N: past-label ridge correction from received timestamped neighbor packets.
6. GAMA compile/runtime/GIS and regression of existing ideal benchmark.
7. Prequential and closed-loop controlled experiments; document measured limits.

## Mandatory acceptance amendments

* Replay needs a development-calibrated similarity threshold. Threshold absent,
  cold start, insufficient horizon, or no accepted scenarios => labelled physical
  fallback, never unqualified replay waiting. Preserve every historical session's
  arrival offset and energy. Record minimum distance and accepted scenario count.
* Train correction on workload residuals, but select hyperparameters on development
  workload AND waiting errors. Lock selected settings before held-out evaluation.
  B4-N is opt-in, B4 remains main. A lower workload MAE alone is insufficient.
* Evaluate fixed traces prequentially and policy-induced arrivals in closed loop.
  Include simultaneous recommendations, bursts, shifts and oscillation metrics.
* Behavior modes are conditional experiments, not empirical compliance models.
* Feasible-set normalization is main; Pareto-set normalization is an ablation.
  Distance-proportional energy duplicates no influence under maximum regret.
* No economic/weighted-sum defaults. Such comparisons require explicit weights.
* No intention is added to B4 demand forecast. No recommendation hard inbound.
* Read-only shadow, dedicated output version, explicit fallback/cache/communication
  metadata, unmatched/unresolved requests counted.

## Development defaults (synthetic, subject to held-out validation)

Five-minute bins; local moving-average window 12 closed bins; replay requires
24 closed bins and 20 past arrivals; up to 20 nearest historical windows. Replay
threshold starts UNCONFIGURED (-1); calibrate on development before replay claims.
Fixed road-time graph, three outgoing neighbors then symmetrize. Ridge starts
zero until max(50, 5p) matured labels, positive regularization explicit. Station
model sees only locally observed arrivals and packets received by issue time.
