TASK: REPLACE RANDOM CHARGING SCHEDULES WITH
SOC-DRIVEN AND PERSONAL ACTIVITY-BASED CHARGING

ROLE

You are a Senior GAMA/GAML Engineer,
EV Charging Simulation Researcher,
and Scientific Software Architect.

Modify the CURRENT GAMA RANR-AW project directly.

IMPORTANT:

The previous charging-demand mechanism based on
random charging schedules is no longer valid.

The new system must generate charging requests
from actual EV energy needs and individual
activity schedules.

Do not create a second implementation.

Do not mix old scheduling logic with the
new SOC-driven charging behavior.

Inspect the existing repository and implement
the changes directly.

====================================================
1. CRITICAL ARCHITECTURAL CHANGE
====================================================

OLD MECHANISM — REMOVE:

Random charging opportunity schedule
    -> Check whether EV needs charging
    -> Generate charging request

NEW MECHANISM — IMPLEMENT:

Individual EV SOC
    +
Individual charging threshold
    +
Current activity state
    +
Upcoming trip energy requirement
    +
Personal or taxi shift schedule
    ->
Charging decision
    ->
Charging request
    ->
RANR-AW recommendation

Charging demand must now emerge naturally
from the simulated EV population.

There must be NO independent random charging
opportunity schedule controlling when an EV
is allowed to request charging.

Do not require a scheduled charging opportunity
before an EV can request charging.

Do not generate random charging requests simply
to satisfy a predefined daily request count.

Do not artificially modify SOC to create demand.

Charging requests must originate from the
physical state and actual needs of existing EVs.

====================================================
2. PRESERVE ALREADY WORKING FUNCTIONALITY
====================================================

The low-SOC charging behavior has already
passed an initial test.

Current verified behavior:

- An EV with low SOC can request charging
  without a random charging schedule.
- The EV can receive charging energy.
- The EV remains in the simulation afterward.

Do not break these working behaviors.

Continue implementing and validating:

A. Long-trip energy feasibility.

B. Charging retry after deferral.

C. Personal activity-based charging decisions.

D. Taxi shift-based charging decisions.

E. Correct charging lifecycle transitions.

Preserve working behavior wherever possible.

====================================================
3. INDIVIDUAL CHARGING SOC THRESHOLDS
====================================================

Each EV must have an individual,
persistent SOC charging threshold.

Sample the threshold once during vehicle
initialization.

Do not regenerate it every cycle.

PRIVATE EV DISTRIBUTION:

SOC interval      Probability

10–20%            5%
20–30%            20%
30–40%            35%
40–50%            25%
50–60%            10%
60–70%            5%

ELECTRIC TAXI DISTRIBUTION:

SOC interval      Probability

10–20%            5%
20–30%            10%
30–40%            20%
40–50%            35%
50–60%            20%
60–70%            10%

Within the selected interval, sample an
individual threshold.

Store:

soc_request_threshold

This attribute belongs to the vehicle.

It must not change every simulation cycle.

The distributions are configurable research
assumptions, not verified empirical statistics.

====================================================
4. AUTOMATIC SOC-BASED CHARGING REQUESTS
====================================================

An EV should normally consider charging when:

soc_current <= soc_request_threshold

However, charging need alone is not sufficient
to start a charging session.

Check:

- Whether the EV already has an active request.
- Whether the EV is traveling to a station.
- Whether the EV is waiting.
- Whether the EV is charging.
- Whether a charging decision is already pending.
- Whether its current activity permits charging.

When charging is needed, create or maintain
one charging intent for that EV.

Do not create a new request every cycle
while SOC remains below the threshold.

Use a clear charging state machine.

Suggested states:

NO_CHARGING_NEED
CHARGING_NEEDED
REQUEST_PENDING
TRAVELING_TO_CS
QUEUING
CHARGING
CHARGING_COMPLETED
CHARGING_DEFERRED
CHARGING_UNAVAILABLE
STRANDED

Adapt these names to the existing codebase.

Reuse existing states where appropriate.

Do not duplicate equivalent state variables.

====================================================
5. PRIVATE EV PERSONAL ACTIVITY SCHEDULES
====================================================

Private EV charging behavior must consider
the vehicle's individual activity schedule.

Examples of activities:

- Traveling to work.
- Traveling home.
- Shopping.
- Personal trips.
- Parking.
- Preparing for an upcoming journey.

Each EV should have an individual activity
and trip schedule.

These schedules describe mobility behavior.

They must NOT be random charging schedules.

Charging decisions should be evaluated:

1. When SOC crosses the individual threshold.

2. Before starting a planned trip.

3. When arriving at a suitable activity location.

4. After completing a trip.

5. When a previously deferred charging need
   becomes eligible for reconsideration.

Avoid unnecessary complete reevaluation
every simulation cycle.

If the EV is parked with low SOC,
it may generate a charging request.

If the EV is currently traveling,
follow physically valid routing and
activity-transition behavior.

Do not teleport the EV to a station.

====================================================
6. ELECTRIC TAXI SHIFT SCHEDULES
====================================================

Electric taxis must use their own
operational behavior.

Consider:

- Current SOC.
- Individual charging threshold.
- Current passenger-service state.
- Remaining shift duration.
- Break periods.
- Upcoming trip requirements.
- Energy reserve.
- Charging availability.

Taxi charging should be possible:

- Before starting a shift.
- During suitable breaks.
- Between passenger trips.
- When SOC becomes insufficient for
  continued service.

Do not force an occupied taxi to abandon
a passenger trip merely to trigger charging.

Do not generate artificial passenger trips
solely to consume battery energy.

A taxi may prefer charging before a long shift,
even if SOC is above its normal threshold.

Taxi charging decisions must remain compatible
with its actual operational schedule.

Private EVs and taxis should share the same
physical charging implementation.

Their behavioral decision rules may differ.

====================================================
7. LONG-TRIP ENERGY FEASIBILITY
====================================================

THIS IS A CRITICAL REQUIREMENT.

SOC percentage alone is not sufficient
to determine whether a trip is feasible.

An EV with SOC above 30% may still lack
enough energy for a long upcoming trip.

Before starting a planned trip, estimate:

E_available =
    soc_current * battery_capacity_kWh

E_trip =
    predicted energy consumption
    along the planned road-network route

E_reserve =
    required battery safety reserve

A trip is feasible only if:

E_available >= E_trip + E_reserve

Use physically meaningful route distances
and vehicle energy consumption.

Do not use arbitrary straight-line distance
when a road-network route is available.

IMPORTANT:

If SOC = 35% but the upcoming trip requires
more energy than the EV safely has available,
the trip must NOT be allowed to proceed
as though the battery were sufficient.

Instead:

1. Identify the energy insufficiency.

2. Create or maintain a charging need.

3. Determine whether the EV can safely
   reach a compatible charging station.

4. Request a recommendation if needed.

5. Defer or modify the planned trip according
   to the existing activity model.

6. Resume the trip after sufficient charging
   energy becomes available.

Do not automatically cancel a feasible trip
just because it is long.

If enough energy and safety reserve are
available, allow the trip to proceed.

Use the planned trip's actual energy
requirement rather than a fixed SOC cutoff.

Do not use privileged future knowledge.

Only use the EV's currently known
planned trip information.

====================================================
8. CHARGING TARGET SOC
====================================================

Each EV must have its own preferred
charging target SOC.

PRIVATE EV TARGET DISTRIBUTION:

80%       30%
85%       25%
90%       25%
95%       10%
100%      10%

ELECTRIC TAXI TARGET DISTRIBUTION:

70%       10%
80%       25%
90%       35%
95%       15%
100%      15%

These are configurable initial assumptions.

Do not force every EV to charge to 80%.

Do not force every taxi to charge to 100%.

Private EVs may use a persistent preferred
charging target.

Taxi session targets may be adjusted using
legitimate current shift and break constraints.

The selected charging target must respect
the energy needed for the EV's planned
activities and safety reserve.

If an activity requires more energy than
the selected target provides, handle the
conflict explicitly.

Do not silently authorize an infeasible trip.

Do not increase SOC without actual charging.

====================================================
9. CHARGING ENERGY AND PHYSICAL PROCESS
====================================================

Calculate required battery energy:

E_required =
    battery_capacity_kWh
    * max(0, soc_target - soc_at_arrival)

SOC at arrival may be lower than SOC
when the charging request was created.

An EV must physically reach a station.

It must obtain an available compatible port
before charging.

Respect:

- Station port power.
- EV charging power limits.
- Available station power.
- Charging efficiency.
- SOC-dependent charging taper,
  if supported by the current model.

Update SOC according to actual charged energy.

Stop charging upon:

- Reaching target SOC.
- A physically valid interruption.
- Another explicitly defined termination event.

Release the charging port correctly.

Keep the EV agent alive.

After charging, continue the personal trip
or taxi activity lifecycle.

====================================================
10. CHARGING DEFERRAL AND RETRY
====================================================

THIS IS A CRITICAL REQUIREMENT.

A deferred EV must not become permanently stuck.

Possible deferral reasons include:

- EV currently unavailable.
- Taxi serving a passenger.
- No feasible charging station.
- Driver chooses to defer.
- Charging station becomes unavailable.
- Charging would conflict with activity timing.

When charging is deferred:

1. Preserve the existing charging need.

2. Record the deferral reason.

3. Record the original charging intent ID.

4. Determine an appropriate retry condition.

5. Do not repeatedly create new requests
   every simulation cycle.

Retry should be triggered by meaningful events:

- Activity completion.
- End of passenger trip.
- Start of a break.
- Reaching an eligible parking location.
- Change in station availability.
- Expiration of a bounded retry cooldown.
- Increased energy urgency.

Use configurable retry intervals and
bounded backoff where appropriate.

Do not indefinitely suppress urgent charging
because of an ordinary cooldown.

Prevent duplicate requests.

Prevent infinite recommendation loops.

Prevent a vehicle from remaining forever in
CHARGING_DEFERRED without reevaluation.

However, do not guarantee successful charging
when no physically feasible option exists.

Record unresolved or stranded cases correctly.

====================================================
11. SEPARATE CHARGING NEED FROM REQUEST
====================================================

Maintain distinct concepts:

CHARGING NEED:
An EV requires or prefers charging.

CHARGING INTENT:
The EV has decided to seek charging.

CHARGING REQUEST:
An actual request sent to the decentralized
recommendation system.

CHARGING SESSION:
Physical charging at a station port.

These are not interchangeable.

An EV may have a charging need but be unable
to send a request immediately because
it is serving a passenger.

An EV may have a request but choose
to defer after receiving a recommendation.

A deferred intent may be retried without
creating duplicate active sessions.

Use stable vehicle IDs and intent IDs.

Count actual recommendation attempts separately
when repeated requests are legitimate.

Do not count every cycle of unresolved
charging need as a new charging request.

====================================================
12. REMOVE LEGACY RANDOM CHARGING SCHEDULES
====================================================

Audit the entire repository for:

- Random charging opportunities.
- Random charging timestamps.
- Per-day charging quotas.
- Forced request generation.
- Random request spawning.
- Scheduled charging events unrelated
  to vehicle energy and activity.
- Obsolete Controlled Demand logic.

Remove the old charging-request generation
mechanism from active execution.

Do not keep it as an alternative workload.

Do not retain hidden configuration modes
that reactivate random charging schedules.

Do not create another implementation
under a new name.

IMPORTANT:

Preserve personal travel schedules.

Preserve taxi shifts.

Preserve legitimate time-of-day traffic patterns.

These are mobility/activity schedules,
not random charging schedules.

The number of charging requests per day
must now emerge from actual vehicle behavior.

Do not enforce the former approximate
760 charging opportunities per day.

That value may be retained only as a
historical calibration reference.

Do not use it as a quota or target
that the simulator must satisfy.

====================================================
13. RANR-AW INTEGRATION
====================================================

Preserve the scientific RANR-AW architecture.

Do not change:

- Fully decentralized CS operation.
- P2P information sharing.
- Outstanding exposure accounting.
- ETA-based queue prediction.
- Five adaptive cost criteria.
- Five adaptive weights.
- Softmax recommendation.
- Non-binding EV behavior.
- CMA-ES optimization framework.

Charging demand must originate from
EV energy requirements.

RANR-AW must not create charging demand.

RANR-AW only handles a valid charging request
and recommends a charging station.

After receiving a recommendation,
the EV makes its own decision.

Do not repeatedly change the EV destination
merely because station costs change.

If replanning is necessary, use explicit
exceptional events and request deduplication.

Preserve physically meaningful battery demand
and expected charging duration in queue prediction.

Do not add electricity-price behavior.

====================================================
14. UNIFIED GAMA SIMULATION
====================================================

Preserve the approved physical model.

Persistent base fleet:

3000 conventional cars
1000 private EVs
700 electric taxis

Total = 4700 vehicles.

Maximum concurrent inbound vehicles = 1410.

Maximum total = 6110.

Preserve:

11 public charging stations.
125 charging ports.

Do not reintroduce soc_fleet.

Do not introduce home charging.

Do not create EVs merely to generate
charging requests.

Do not delete EVs after charging.

Keep individual SOC and vehicle identity
persistent across simulation days.

Apply the same behavior implementation to:

Run me

Collect training data

GAMA Headless execution

Do not duplicate GUI and Headless logic.

Preserve the approved time configuration:

1 minute per cycle.

72 simulated hours.

6 hours warm-up.

60 hours measurement.

6 hours drain.

During warm-up, use normal physical behavior.

During measurement, collect charging outcomes.

During drain, allow existing charging intents,
requests, queues, and sessions to resolve.

Do not generate new independent charging demand
for the measurement population during drain.

Previously generated deferred intents may continue
their resolution under the same original intent ID.

Do not force charging completion at the
end of the drain period.

Handle unresolved outcomes consistently.

====================================================
15. REPRODUCIBILITY AND RNG PERFORMANCE
====================================================

Maintain reproducible behavior.

For paired seeds, preserve:

- Initial vehicle population.
- Vehicle IDs.
- Battery capacities.
- Initial SOC distributions.
- Individual SOC charging thresholds.
- Target SOC preferences.
- Exogenous personal trip schedules.
- Exogenous taxi shifts.
- Inbound traffic generation.

Actual charging requests may legitimately differ
between policies because SOC, travel delays,
and completed charging sessions can diverge.

Do not force identical realized requests
by resetting SOC or creating replacement EVs.

Do not repeatedly reset the global RNG.

Do not repeatedly restore rng_usage
during vehicle movement.

Use reproducible event-level randomness
or appropriately isolated random streams.

Do not introduce expensive random-state
restoration loops.

====================================================
16. RECOLLECT TRAINING DATA FOR THREE SEEDS
====================================================

The charging-demand generation mechanism
has fundamentally changed.

Therefore, all calibration/training data
generated using the old random charging
schedule must be considered obsolete
for the revised physical model.

Preserve historical outputs separately,
but do not mix them with new datasets.

After implementation and successful validation:

1. Identify the three configured
   calibration/training seeds.

2. Verify their configurations.

3. Run the new GAMA model for each seed.

4. Collect fresh data using the revised
   SOC-driven charging mechanism.

5. Record the code version and configuration.

6. Verify dataset completeness.

7. Verify SOC and charging outcome consistency.

8. Verify charging demand arises from
   SOC and activity conditions.

9. Verify no legacy random charging
   schedule generated any request.

10. Save all three datasets with clear
    provenance and version metadata.

Do not reuse old charging-demand calibration
statistics as if they were generated by
the new model.

Do not launch full CMA-ES optimization.

If data collection cannot execute,
report the exact blocker rather than
claiming that the datasets were collected.

====================================================
17. REQUIRED TESTS
====================================================

Implement and execute tests covering:

TEST 1:
Low-SOC EV autonomously creates a valid
charging request without a random
charging opportunity.

TEST 2:
An EV with SOC above 30% detects that
an upcoming long trip needs more energy
than currently available.

TEST 3:
An EV with enough energy is allowed
to complete a feasible long trip.

TEST 4:
Private EV charging follows individual
SOC and activity preferences.

TEST 5:
Taxi charging respects shift schedules
and passenger-service constraints.

TEST 6:
Deferred charging requests are retried
under valid conditions.

TEST 7:
An EV cannot create duplicate active
charging requests.

TEST 8:
Retry logic does not create an
infinite request loop.

TEST 9:
SOC decreases according to actual
travel energy consumption.

TEST 10:
SOC increases only during physically
valid charging sessions.

TEST 11:
An EV remains alive after charging.

TEST 12:
Charging ports are correctly allocated
and released.

TEST 13:
No random charging schedule remains
active anywhere in the project.

TEST 14:
Charging demand is not forced to
match a daily request quota.

TEST 15:
Private EV and taxi SOC distributions
remain distinct and reproducible.

TEST 16:
Run me and Collect training data use
the same charging behavior.

TEST 17:
No repeated rng_usage restoration
occurs in the vehicle movement loop.

TEST 18:
All three new training datasets use
the revised model and correct seeds.

TEST 19:
No charging decision depends on
electricity prices.

TEST 20:
RANR-AW remains decentralized,
non-binding, and physically consistent.

Report actual test outcomes.

Do not fabricate results.

====================================================
18. IN-PLACE REFACTORING RULES
====================================================

Inspect the existing source code first.

Identify all active charging-demand generators
and their dependencies.

Create a recoverable Git checkpoint.

Update the existing authoritative modules.

Do not create:

charging_v2
charging_new
charging_final

or equivalent duplicate implementations.

Remove obsolete random charging scheduling
code after replacement validation.

Update callers, configuration, tests,
GUI, Headless, and documentation.

Do not remove unrelated working functionality.

Do not destroy historical simulation results.

====================================================
FINAL ACCEPTANCE CRITERIA
====================================================

The project is acceptable only when:

1. Charging requests are SOC-driven.

2. Personal EV mobility schedules affect
   charging decisions.

3. Taxi shift schedules affect charging decisions.

4. Random charging schedules no longer control
   charging request generation.

5. Long-trip energy feasibility is checked.

6. Vehicles above 30% SOC can request charging
   when upcoming trips require more energy.

7. Deferred charging needs are reevaluated.

8. No duplicate or infinite request loops exist.

9. All SOC changes are physically valid.

10. Vehicles remain persistent after charging.

11. The existing RANR-AW method is preserved.

12. GUI and Headless share one implementation.

13. No legacy charging implementation remains active.

14. New calibration/training data is collected
    using all three configured seeds.

15. The new implementation is validated
    before CMA-ES training.

EXECUTE THE MODIFICATIONS DIRECTLY.

Do not stop after providing recommendations.

Do not create another project version.

Do not preserve legacy random charging
schedules merely for backward compatibility.

Implement, test, and report actual results.