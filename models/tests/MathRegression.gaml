model math_regression
import "../ConvexAssignment.gaml"

global {
    init {
        write "MATH_START";
        // Phantom capacity: 50 service units before an end-of-bin arrival cannot erase it.
        batch_n <- 1;batch_h <- 2;batch_theta <- 0.1;
        create assignment_station with: [sid::0,capacity::[50.0,5.0],inbound::[20.0,0.0]];
        create assignment_edge with: [n::0,owner::assignment_station[0],hbin::0,demand::0.0,cost::1.0];
        do prepare_solver;
        ask assignment_station { do recompute_profile(false); }
        write "MATH_PROFILE " + assignment_station[0].backlog_profile + " price=" + assignment_station[0].price_profile;
        assert assignment_station[0].backlog_profile = [20.0,15.0];
        assert abs(assignment_station[0].price_profile[0] - 1.0/3.0) < 1e-10;
        // 100 EVs with .51/.49 must produce 51/49, not 100/0.
        do clear_snapshot;batch_n <- 100;batch_h <- 1;
        create assignment_station number: 2 {capacity<-[0.0];inbound<-[0.0];}
        loop m from: 0 to: 1 { assignment_station[m].sid <- m; }
        loop n from: 0 to: 99 {
            create assignment_edge with: [n::n,owner::assignment_station[0],hbin::0,demand::1.0,cost::1.0];
            create assignment_edge with: [n::n,owner::assignment_station[1],hbin::0,demand::1.0,cost::1.0];
        }
        do prepare_solver;
        ask assignment_edge { x <- owner.sid = 0 ? 0.51 : 0.49; }
        do recover_integer;
        write "MATH_ROUND " + sum(assignment_station[0].local_edges collect each.z) + "/" + sum(assignment_station[1].local_edges collect each.z);
        assert sum(assignment_station[0].local_edges collect each.z) = 51.0;
        assert sum(assignment_station[1].local_edges collect each.z) = 49.0;
        assert repair_moves = 0;
        assert repair_fallback_checks > 0;
        // Two disconnected singleton components and zero capacity.
        do clear_snapshot;batch_n<-2;batch_h<-2;
        create assignment_station number: 2 {capacity<-[0.0,0.0];inbound<-[0.0,0.0];}
        loop m from: 0 to: 1 { assignment_station[m].sid <- m; }
        loop n from: 0 to: 1 {create assignment_edge with:[n::n,owner::assignment_station[n],hbin::n,demand::10.0,cost::1.0];}
        do solve_snapshot;
        write "MATH_ZERO " + solver_status + " " + primal_residual + " " + relative_gap;
        assert solver_status = "converged";
        assert communication_messages = 0;
        do recover_integer;
        assert assignment_station[0].component = 0 and assignment_station[1].component = 1;
        batch_theta <- 0.0;
        do solve_snapshot;
        assert solver_status = "converged";
        assert primal_residual <= 1e-6;
        write "MATH_REGRESSION_PASS";
    }
}
experiment "math" type: gui { float seed <- 42.0; }
