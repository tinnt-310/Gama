These native fixtures add evidence without changing the frozen worker's models.

`RanrPhysicalPredictionReview.gaml` compares `ranr_estimate` mean/P95 against a
real EV's charging wait, and compares predicted externality against two physical
stations with and without the inserted EV. The controlled result is 10 minutes
for each quantity. It also exercises all 20 adaptive coefficients and the fixed
reference row. This is a deterministic counterexample test, not field forecast
validation or Monte Carlo convergence.

`RanrAdaptiveFeatureReview.gaml` loads the accepted observation-v5 calibration
from the sibling delivery directory `accepted_data_v5/calibration.json`. It
checks the native state construction under controlled load, request intensity,
response uncertainty and information age. Its five designed state vectors have
rank 5. Learned gains and empirical identifiability remain outside this test.

Both run through `ranr.gama.validation.run_model`, using experiments
`physical_prediction_review` (46 steps) and `adaptive_feature_review` (one step).
Delivery evidence records each fixture's SHA-256 explicitly because these
additional test files are outside the production `models/` provenance glob.
The original full native suite has not been relabeled as executing this commit.

`RanrPairedPhysicalReplay.gaml` replays sealed physical arrival/SOC/power and
cancellation schedules into two actual charging-station branches, removing only
the selected EV in the control branch. It does not call `ranr_estimate` or use
shadow output as truth. The Python delivery harness reconstructs inputs and
checks native insertion-branch waiting against observed service starts before
scoring H. Engineering checks on calibration traces reproduced130 observed
waiting times exactly across sid0/2/7/9. These checks are not independent R01
acceptance; that protocol uses920001–920006 after its prerequisite gate passes.
