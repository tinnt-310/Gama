model gis_coordination_benchmark
import "main.gaml"

global {
    int cars <- 0;
    int privates <- 0;
    int taxis <- 0;
    bool have_rush <- false;
    bool coordination_enabled <- false;
    string oracle_backend <- "fixed_port";
    string run_prefix <- "../outputs/controlled_gis";
    float ele_car_speed <- 36.0;
    list<string> demand_ids <- [];
    reflex inject_controlled_requests when: cycle = 0 {
        charging_station near <- first(list(charging_station) where (each.name = "cs_1"));
        // Identical 30-minute physical commitments on every port at the nearest site.
        loop while: near.find_available_port() > 0 {
            float energy <- charge_efficiency*near.find_available_port()*0.5;
            create private_ev with: [location::near.closest_intersection.location,
                battery_level::(80.0-100.0*energy/battery_capacity_kwh)] {
                do begin_request; current_station <- near; commit_time <- 0.0; do start_charging;
            }
        }
        string trace <- "request_id,request_min,origin_x,origin_y,requested_kwh,workload_service_min\n";
        create private_ev with: [location::near.closest_intersection.location,battery_level::35.0] {
            do begin_request; world.demand_ids << request_id;
        }
        elecar ev <- last(ev_population);
        trace <- trace + ev.request_id + ",0.0," + ev.location.x + "," + ev.location.y + "," + ev.requested_energy + "," + ev.workload + "\n";
        save trace to: run_prefix + "_demand.csv" format: "text";
        do coordinate_batch;
        assert length(ev.candidates) = 11;
        if assignment_policy = "nearest" { assert ev.current_station = near; }
        else { assert ev.current_station != near; }
    }
    reflex verify_gis_benchmark when: cycle = 4800 {
        assert empty(ev_population where (each.request_id in demand_ids and each.session_state != "completed"));
        assert empty(list(charging_station) where (!empty(each.waiting_queue) or !empty(each.charging_vehicles) or !empty(each.inbound_work)));
        do export_run;
        write "GIS_COORDINATION_BENCHMARK_PASS";
    }
}
experiment "controlled_gis" type: gui {
    float seed <- 42.0;
    parameter "Policy" var: assignment_policy;
    parameter "Solver iteration budget" var: solver_limit;
}
