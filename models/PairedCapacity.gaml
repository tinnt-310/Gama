model paired_capacity
import "ConvexAssignment.gaml"

global {
    init {
        fixture_seed <- 7;
        do create_fixture;
        rounding_rng <- 42.0;
        artifact_prefix <- "../outputs/paired_base";
        do solve_snapshot;do recover_integer;do export_snapshot;
        // Preserve every edge, workload, ETA bin, cost and inbound value. Change only C.
        ask assignment_station {
            loop h from: 0 to: batch_h-1 {
                capacity[h] <- sid=0 ? 0.0 : (sid=1 ? 2.0*capacity[h] : capacity[h]);
            }
        }
        rounding_rng <- 42.0;
        fixture_capacity <- "paired_changed";
        artifact_prefix <- "../outputs/paired_changed";
        do solve_snapshot;do recover_integer;do export_snapshot;
        write "PAIRED_CAPACITY_PASS";
    }
}
experiment "paired" type:gui {float seed<-42.0;}
