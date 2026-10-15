model recommendation_benchmark
import "Recommendation.gaml"

global {
    geometry shape <- rectangle(100000,1000);
    int benchmark_stations <- 2;
    string runtime_mode <- "RECOMMENDATION_RUNTIME";
    string oracle_backend <- "fixed_port";
    string charging_goal <- "target_soc";
    float step <- 60.0;
    float ele_car_speed <- 36.0;
    string waiting_forecast_mode <- "B4";
    string benchmark_case <- "feedback_shift";
    float run_hours <- 48.0;
    bool benchmark_done <- false;
    float next_demand <- 0.0;
    float demand_rng <- 42.0;
    int spawned_requests <- 0;
    int demand_exported <- 0;
    list<string> benchmark_request_ids <- [];
    string demand_trace_rows <- "";
    bool isolate_run_outputs <- true;
    bool cleanup_benchmark_vehicles <- true;
    float demand_uniform {
        float value <- 1664525.0*demand_rng+1013904223.0;
        demand_rng <- value-floor(value/4294967296.0)*4294967296.0;
        return demand_rng/4294967296.0;
    }
    init {
        demand_rng <- seed;
        run_prefix <- "../outputs/recommendation_"+benchmark_case+"_"+(runtime_mode = "IDEAL_COORDINATED_ASSIGNMENT" ? "IDEAL_"+assignment_policy : waiting_forecast_mode+"_"+recommendation_method)+"_"+int(seed);
        do prepare_run_output;
        create intersection number: benchmark_stations+2 { location <- {100.0+index*600.0,100.0}; }
        loop k from: 0 to: benchmark_stations {
            create road with: [shape::polyline([intersection[k].location,intersection[k+1].location]),num_lanes::2];
            create road with: [shape::polyline([intersection[k+1].location,intersection[k].location]),num_lanes::2];
        }
        road_network <- as_driving_graph(road,intersection) with_shortest_path_algorithm "Dijkstra";
        create building with: [location::intersection[0].location,closest_intersection::intersection[0],build_type::1];
        buildings_type_1 <- list(building); buildings_type_2 <- list(building); buildings_type_3 <- list(building);
        create charging_station number: benchmark_stations {
            name <- benchmark_stations = 2 ? (index = 0 ? "west" : "east") : "station_"+index;
            closest_intersection <- intersection[index+1]; location <- closest_intersection.location;
            port_60 <- 1;
        }
        if runtime_mode = "RECOMMENDATION_RUNTIME" { do initialize_recommendation; } else { do initialize_coordination; }
        save "request_id,time_min,origin,soc_pct\n" to: run_prefix+"_demand.csv" format: "text";
    }
    reflex generate_demand when: !benchmark_done and time >= next_demand and time < run_hours*3600.0 {
        float hour_now <- time/3600.0;
        int count <- benchmark_case = "light" ? 1 : 2;
        if benchmark_case in ["burst","feedback_shift"] and hour_now mod 12.0 >= 6.0 and hour_now mod 12.0 < 8.0 { count <- 6; }
        int origin <- benchmark_case = "feedback_shift" and hour_now >= 24.0 ? benchmark_stations+1 : 0;
        loop k from: 1 to: count {
            float initial_soc <- 55.0+15.0*demand_uniform();
            create private_ev with: [location::intersection[origin].location,home::building[0],battery_level::initial_soc] {
                do begin_request;
                world.benchmark_request_ids << request_id;
                world.demand_trace_rows <- world.demand_trace_rows+request_id+","+time/60.0+","+origin+","+initial_soc+"\n";
            }
            spawned_requests <- spawned_requests+1;
        }
        next_demand <- time+900.0;
        if demand_trace_rows != "" { save demand_trace_rows to: run_prefix+"_demand.csv" format: "text" rewrite: false; demand_trace_rows <- ""; }
        // Demand arrives after the base recommendation reflex: next epoch is an explicit one-tick delay.
    }
    reflex retire_completed when: cleanup_benchmark_vehicles {
        ask ev_population where (each.session_state in ["completed","stranded","cancelled"]) { do unregister; do die; }
    }
    reflex finish_benchmark when: !benchmark_done and time >= run_hours*3600.0 {
        benchmark_done <- true; coordination_enabled <- false;
        if runtime_mode = "RECOMMENDATION_RUNTIME" { do export_recommendations; }
        do export_run;
        string summary <- "station,arrived,started,completed,peak_queue,grid_kwh\n";
        loop station over: charging_station { summary <- summary+station.name+","+station.arrived_customer+","+station.vehicle_charged+","+station.served_customer+","+station.peak_physical_queue+","+station.power_consumed+"\n"; }
        save summary to: run_prefix+"_physical_summary.csv" format: "text";
        write (runtime_mode = "IDEAL_COORDINATED_ASSIGNMENT" ? "IDEAL_COORDINATED_BENCHMARK_PASS " : "RECOMMENDATION_BENCHMARK_PASS ") + run_prefix;
    }
}
experiment "recommendation_benchmark" type: gui {
    float seed <- 42.0;
    parameter "Runtime" var: runtime_mode;
    parameter "Ideal solver iterations" var: solver_limit;
    parameter "Station count" var: benchmark_stations;
    parameter "Estimator" var: waiting_estimator_mode;
    parameter "Fallback" var: ood_fallback_mode;
    parameter "Degree" var: communication_degree;
    parameter "Forecast" var: waiting_forecast_mode;
    parameter "Policy" var: recommendation_method;
    parameter "Case" var: benchmark_case;
    parameter "Hours" var: run_hours;
    parameter "Replay scenarios" var: replay_scenarios;
    parameter "History window" var: observation_window;
    parameter "Candidates" var: candidate_mode;
    parameter "Cold start bins" var: observation_min_bins;
    parameter "Threshold" var: replay_similarity_threshold;
    parameter "Correction enabled" var: neighbor_correction_enabled;
    parameter "Neighbor ridge" var: ridge_penalty;
    parameter "Normalization" var: normalization_mode;
    parameter "Information" var: information_mode;
    parameter "Behavior" var: ev_choice_mode;
    parameter "Neighbor latency" var: neighbor_delay_minutes;
    parameter "Cleanup" var: cleanup_benchmark_vehicles;
}
