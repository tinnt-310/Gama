model phase_a
import "ConvexAssignment.gaml"

global {
    init {
        // Standalone mock workload experiments. These are not physical waiting ground truth.
        loop case_id from: 0 to: 7 {
            fixture_seed <- 7 + case_id;
            rounding_rng <- 42.0;
            fixture_n <- case_id >= 4 ? (case_id >= 6 ? 30 : 20) : 10;
            fixture_m <- case_id >= 6 ? 5 : 3;
            fixture_k <- case_id = 7 ? 2 : 3;
            fixture_h <- case_id >= 4 ? 8 : 4;
            fixture_capacity <- case_id = 1 ? "drop" : (case_id = 2 ? "recovery" : (case_id = 3 ? "heterogeneous" : "constant"));
            artifact_prefix <- "../outputs/phase_a_" + case_id;
            do create_fixture;
            do solve_snapshot;
            do recover_integer;
            do export_snapshot;
            write "PHASE_A_CASE " + case_id + " status=" + solver_status + " iterations=" + solver_iterations;
        }
        write "PHASE_A_PASS";
    }
}
experiment "phase_a" type: gui { float seed <- 42.0; }
