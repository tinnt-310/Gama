# Exact numerical formulation and implementation limits

## Workload units and physical forecast

C, d, H_vir, A, q and d_ref are equivalent reference-service minutes. `d=60*requested_kWh/(reference_efficiency*reference_power_kW)`, frozen per request. Physical efficiency can change without redefining workload; available port time is converted by `physical_efficiency*port_power/(reference_efficiency*reference_power)`. Epigraph Q=q/d_ref is dimensionless. Delta, travel, F and d*pi have units minutes; pi is minutes per equivalent service-minute. Grid kWh is logged separately and is not a third assignment-objective term.

Fixed-port C is a read-only FIFO shadow of actual physical commitments and port-release ticks. It excludes inbound, which is injected only through H_vir. Mock C remains prescribed capacity. Both use the same interval-causal recursion. F and d*pi are congestion surrogates, never individual predicted waiting. Event travel uses arrival−commit; waiting uses service-start−arrival, including zero waits.

## Causal congestion and prices

For fixed nonnegative interval capacities C and arrivals A, `q[h]=A[h]+max(0,q[h−1]−C[h])`, q[−1]=0. Capacity in h acts on backlog present before end-of-bin arrivals. In particular A=20, C=50, previous q=0 gives q=20, not zero. No service is saved for a later arrival.

q is convex by induction and F is a positive weighted sum. Let `alpha[h]=1` if `q[h−1]>C[h]`, else 0 (inactive at equality). A valid subgradient obeys `pi[H−1]=Delta/d_ref`, `pi[h]=Delta/d_ref+alpha[h+1]*pi[h+1]`. An EV's congestion direction is d*pi[ETA bin], with no second downstream-price sum.

## Epigraph PDHG

Scale `Q=q/d_ref`, a=d/d_ref. For each station/bin:

```
Σ a_e x_e − Q_h                 ≤ −H_h/d_ref
Σ a_e x_e + Q_(h−1) − Q_h       ≤ (C_h−H_h)/d_ref
Σ_(e incident to EV n) x_e      = 1
```

Q_(−1)=0. Stack these as Kp≤b and equality rows. The primal objective is `c*x + theta*Σ x ln x + Delta*Σ Q`. The algorithm's domains are x≥0 and 0≤Q≤U, where `U=(Σ H + Σ_candidate_edges d)/d_ref` safely contains every feasible causal backlog. x≤1 follows from row simplex feasibility. Entropy remains convex and continuous at zero with 0 ln 0=0.

All duals start at zero; x starts uniformly per candidate set and Q starts at zero; bar starts equal to primal. At each synchronized iteration:

1. `lambda ← max(0,lambda+sigma*(K_inequality*bar−b))`.
2. Equality ν copies at every candidate station update by `sigma*(sum shared bar_x−1)`; every candidate station receives all other candidate contributions. Identical initialization and barriers reconcile these copies. This is a replicated equality dual PDHG implementation on each candidate clique, rather than an asynchronous gossip method.
3. `v←p−tau*K^T*dual`; apply entropy prox to `v_x−tau*c`, and clamp `v_Q−tau*Delta` to [0,U].
4. `bar←2*new−old`.

The scalar prox solves `exp(l)+tau*theta*(1+l)=v` in log coordinates by 52 bisections, x=exp(l). theta=0 uses max(0,v). Bounds [−745,ln(max(1,v))] handle double precision; underflow is allowed for negligible coordinates. Both Python and GAML implement these same equations.

Raw x can exceed one while equality feasibility is being solved; extrapolated xbar can also leave the feasible domain. Reported/recovered xp is projected onto the simplex and explicitly checked in [0,1] with row sum one. Physical decisions are binary z. The feasible primal has the same simplex domain even though this splitting does not box the individual x prox; see REVIEW_FINDINGS.md for the distinction and regression.

`tau=sigma=.99/||K||F` ensures tau*sigma*||K||²<1. With a nonempty finite candidate simplex, nonnegative finite inputs, strictly positive bin duration, bounded Q containing causal backlogs and synchronous complete shared-candidate exchanges, the finite-dimensional convex saddle problem meets the standard PDHG step condition. Positive entropy gives unique assignment x; no linear rate, asynchronous/delayed-network theorem or new distributed-algorithm claim is made here.

Checks every 20 iterations: raw equality/inequality maximum residual ≤1e−6 and certified relative gap ≤1e−7 (stricter than the plan's 1e−5 reference criterion). Stopping also requires consensus-copy disagreement ≤1e−6; it is exported separately. Project x onto row simplices for a feasible reported objective and recovery; do not overwrite raw x. Recompute causal backlog instead of using potentially infeasible epigraph iterates. The default limit is 20,000; theta=0 benchmark fixtures explicitly use 200,000. Timeout remains a distinct outcome.

## Valid lower bound

For any lambda≥0 and unrestricted equality ν, infimize the Lagrangian over the box x∈[0,1], Q∈[0,U]. This box contains all feasible primal points even though the numerical prox does not impose x≤1. Put g=c+K_x^T*y and gQ=Delta+K_Q^T*y:

- theta>0: xmin=min(1,exp(−1−g/theta)); sum g*xmin+theta*xmin*ln(xmin).
- theta=0: sum min(0,g).
- Q contribution: U*sum min(0,gQ).
- Subtract b*y, including each equality constant ν exactly once.

This is a valid dual/Lagrangian LB at every iteration, not an approximate primal value. Since entropy is negative on simplices, `J0*−theta Σ ln K_n ≤ Jtheta* ≤ J0*`. An entropy dual LB therefore already lower-bounds the unregularized integer optimum; subtracting bias again is unnecessary and looser. Feasible integer z yields UB from the same frozen snapshot.

## Recovery

GKPS operates on fractional EV–station edges. Alternate ± updates around an even cycle or along a maximal forest path; choose step probabilities to preserve marginals. Integral EV degree one is preserved. Station counts have floor/ceil behavior before repair; heterogeneous workload is not exactly balanced. Independent RNG state is exported. Each overlap component's smallest-ID station leads recovery; other stations retain local capacity and compute exact local relocation differences.

Traversal now validates active-ancestor cycle closure, bounded parent ancestry, no repeated path nodes/edges, even cycle parity and positive step sizes. Every accepted rounding step strictly eliminates at least one fractional edge; failure raises rather than continuing an empty/stalled trail. Valid-input probabilities/equations and RNG streams remain the same.

Repair ranks all relocations by current marginal proxy. Exact checks scan top five first, then all remaining moves. Accept strictly below −1e−6 minutes, recompute both affected station profiles and restart. Consequently accepted objectives decrease and termination is a one-exchange local optimum within tolerance. This is not a global approximation guarantee.

## Limits and complexity

One solver update processes O(E+MH) local values and O(Σ_n K_n(K_n−1)) logical messages. Initialization, GAML agent/list filters and simplex/objective checks have extra overhead; the measured runtime includes them. GKPS graph searches and proxy lists are explicit and intended for micro-batches. Exact relocation changes recompute only affected ETA suffixes, but GAML's local-edge filtering is still repeated per bin; further indexing can improve large-batch runtime.

The synchronization driver controls barriers and collects scalar stopping metrics; it does not perform centralized primal/dual updates. Transport is in-process GAMA agent communication. Payload-byte counters model canonical optimization values, not actual socket serialization.

The finite horizon is a workload-holding surrogate, not exact waiting. Fixed-port service is ground truth only for fixed-port events. Prescribed mock C need not equal fixed-port residual service; all mixed runs explicitly label forecast mismatch. There is no evidence about robot SOC, recharge or failure until Gate 8 receives the actual scheduler.

## Offline replay settings

Independent snapshot reproduction reads the exported solver iteration budget and feasibility/gap tolerances from the batch config. Comparing a larger-budget GAML result to a Python prototype stopped at the default 20,000 iterations would otherwise produce a false cross-language mismatch. Physical benchmarks retain the 20,000 default and explicitly report timeout; additional numerical verification uses 200,000 without changing equations, initialization or stopping tolerances.
