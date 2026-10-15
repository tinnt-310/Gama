model coordination_benchmark
import "Coordination.gaml"

global {
    geometry shape <- rectangle(2000,1000);
    string benchmark_case <- "near_busy";
    bool coordination_enabled <- false;
    bool isolate_run_outputs <- true;
    string oracle_backend <- "fixed_port";
    float ele_car_speed <- 36.0;
    list<string> demand_ids <- [];
    init {
        run_prefix <- "../outputs/controlled_" + benchmark_case + "_" + assignment_policy;
        do prepare_run_output;
        create intersection number: 3 { location <- {100.0 + (index = 0 ? 0.0 : (index = 1 ? 300.0 : 900.0)),100}; }
        create road with: [shape::polyline([intersection[0].location,intersection[1].location]),num_lanes::2];
        create road with: [shape::polyline([intersection[1].location,intersection[2].location]),num_lanes::2];
        create road with: [shape::polyline([intersection[2].location,intersection[1].location]),num_lanes::2];
        create road with: [shape::polyline([intersection[1].location,intersection[0].location]),num_lanes::2];
        road_network <- as_driving_graph(road,intersection) with_shortest_path_algorithm "Dijkstra";
        create building with: [location::intersection[0].location,closest_intersection::intersection[0],build_type::1];
        buildings_type_1 <- list(building); buildings_type_2 <- list(building); buildings_type_3 <- list(building);
        create charging_station number: 2 {
            name <- index = 0 ? "near" : "far";
            closest_intersection <- intersection[index+1]; location <- closest_intersection.location; port_60 <- 1;
        }
        if benchmark_case != "light" {
            create private_ev with: [name::"blocker",location::intersection[1].location,home::building[0],battery_level::35.0] {
                do begin_request; current_station <- charging_station[0]; commit_time <- 0.0; do start_charging;
            }
        }
        int requests <- benchmark_case = "burst" ? 4 : 1;
        string trace <- "request_id,request_min,origin_x,origin_y,requested_kwh,workload_service_min\n";
        create private_ev number: requests with: [location::intersection[0].location,home::building[0],battery_level::35.0] {
            do begin_request;
            world.demand_ids << request_id;
        }
        loop ev over: ev_population where (each.request_id in demand_ids) {
            trace <- trace + ev.request_id + ",0.0," + ev.location.x + "," + ev.location.y + "," + ev.requested_energy + "," + ev.workload + "\n";
        }
        save trace to: run_prefix + "_demand.csv" format: "text";
        do coordinate_batch;
        assert empty(ev_population where (each.request_id in demand_ids and each.session_state != "en_route"));
    }
    reflex verify_benchmark when: cycle = 9600 {
        assert empty(ev_population where (each.request_id in demand_ids and each.session_state != "completed"));
        assert empty(list(charging_station) where (!empty(each.inbound_work) or !empty(each.waiting_queue) or !empty(each.charging_vehicles)));
        assert charging_station[0].port_60 = 1 and charging_station[1].port_60 = 1;
        do export_run;
        write "COORDINATION_BENCHMARK_PASS";
    }
}
experiment "controlled" type: gui {
    float seed <- 42.0;
    parameter "Policy" var: assignment_policy;
    parameter "Case" var: benchmark_case;
    parameter "Solver iteration budget" var: solver_limit;
}
