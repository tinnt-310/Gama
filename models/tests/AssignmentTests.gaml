model assignment_tests
import "../ConvexAssignment.gaml"

global {
    init {
        artifact_prefix <- "../../outputs/assignment";
        fixture_seed <- 7;
        do create_fixture;
        do solve_snapshot;
        assert solver_status = "converged";
        assert primal_residual <= 1e-6;
        assert relative_gap <= 1e-5;
        do recover_integer;
        assert lower_bound <= integer_objective + 1e-7;
        loop n from: 0 to: batch_n - 1 {
            assert sum((list(assignment_edge) where (each.n = n)) collect each.z) = 1.0;
        }
        do export_snapshot;
        write "ASSIGNMENT_TESTS_PASS";
    }
}
experiment "assignment" type: gui { float seed <- 42.0; }
