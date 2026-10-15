model solver_safety_regression
import "../ConvexAssignment.gaml"

global {
    action check_degrees {
        ask assignment_edge { assert z = 0.0 or z = 1.0; }
        loop ev_index from: 0 to: batch_n-1 {
            assert sum((list(assignment_edge) where (each.n = ev_index)) collect each.z) = 1.0;
        }
        ask assignment_station {
            float original <- sum(local_edges collect each.xp);
            float rounded <- sum(local_edges collect each.z);
            assert rounded >= floor(original+1e-8) and rounded <= ceil(original-1e-8);
        }
    }
    action round_only {
        do project_assignment;
        ask assignment_edge { z <- xp; }
        ask assignment_station where (each.sid = each.component) { do dependent_rounding; }
        do check_degrees;
        assert rounding_steps <= length(assignment_edge);
    }
    init {
        solver_tau <- 0.2; batch_theta <- 0.25;
        assert prox_entropy(3.0) > 1.0; // Raw iterate domain, never a physical assignment.
        fixture_n <- 1; fixture_m <- 2; fixture_k <- 2; fixture_h <- 1;
        do create_fixture; do prepare_solver;
        ask assignment_edge { x <- owner.sid = 0 ? 1.4 : 0.2; }
        do project_assignment;
        assert sum(list(assignment_edge) collect each.xp) = 1.0;
        assert max(list(assignment_edge) collect each.xp) <= 1.0;
        do round_only;
        // Empty station blocks are valid and do not need recovery or random draws.
        fixture_n <- 1; fixture_m <- 4; fixture_k <- 1;
        do create_fixture; do prepare_solver; do round_only;
        assert rounding_steps = 0;
        // Dense cycles, branching forests, and varying fractional distributions.
        loop case_index from: 1 to: 30 {
            fixture_seed <- case_index; rounding_rng <- float(case_index);
            fixture_n <- 4 + case_index mod 7;
            fixture_m <- 3 + case_index mod 3;
            fixture_k <- 2 + case_index mod 2;
            fixture_h <- 1;
            do create_fixture; do prepare_solver;
            ask assignment_edge { x <- 0.01 + world.fixture_uniform(); }
            loop ev_index from: 0 to: batch_n-1 {
                list<assignment_edge> row <- list(assignment_edge) where (each.n = ev_index);
                float total <- sum(row collect each.x);
                ask row { x <- x/total; }
            }
            do round_only;
        }
        // A long acyclic chain exercises maximal-path traversal without recursion.
        do clear_snapshot; batch_n <- 60; batch_h <- 1;
        create assignment_station number: 61 { capacity <- [0.0]; inbound <- [0.0]; }
        loop station_index from: 0 to: 60 { assignment_station[station_index].sid <- station_index; }
        loop ev_index from: 0 to: 59 {
            create assignment_edge with: [n::ev_index,owner::assignment_station[ev_index],demand::1.0,cost::1.0];
            create assignment_edge with: [n::ev_index,owner::assignment_station[ev_index+1],demand::1.0,cost::1.0];
        }
        do prepare_solver; ask assignment_edge { x <- 0.5; }
        do round_only;
        write "SOLVER_SAFETY_REGRESSION_PASS";
    }
}
experiment "safety" type: gui { float seed <- 42.0; }
