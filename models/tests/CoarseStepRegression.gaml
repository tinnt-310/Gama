model coarse_step_regression
import "../Traffic.gaml"

global {
    float step <- 60.0 #s;
    geometry shape <- rectangle(1000,1000);
    init {
        create intersection with: [location::{100,100}];
        create intersection with: [location::{300,300}];
        create road with: [shape::polyline([{100,100},{100,300},{300,300}]),num_lanes::2];
        road_network <- as_driving_graph(road,intersection) with_shortest_path_algorithm "Dijkstra";
        create building with: [location::{100,100},closest_intersection::intersection[0],build_type::1];
        buildings_type_1 <- list(building); buildings_type_2 <- list(building); buildings_type_3 <- list(building);
        create charging_station with: [location::{300,300},closest_intersection::intersection[1],port_60::1];
        create private_ev with: [location::{100,100},home::building[0],battery_level::79.0] {
            do begin_request;
            current_station <- charging_station[0];
            session_state <- "en_route";
            do compute_path graph: road_network target: intersection[1];
        }
    }
    reflex verify_coarse_step {
        if cycle = 1 {
            assert abs(time - 60.0) < 1e-9;
            assert abs(private_ev[0].total_distance - 400.0) < 1e-6;
            assert abs(private_ev[0].battery_level - 78.88) < 1e-6;
            assert private_ev[0].arrival_time = 1.0 and private_ev[0].service_start = 1.0;
            assert charging_station[0].arrived_customer = 1;
        }
        if cycle = 3 {
            assert charging_station[0].served_customer = 1;
            assert charging_station[0].port_60 = 1;
            assert abs(private_ev[0].delivered_energy - 0.6) < 1e-9;
            assert abs(charging_station[0].power_consumed - 2.0 / 3.0) < 1e-9;
            assert abs(private_ev[0].service_finish - (1.0 + 2.0 / 3.0)) < 1e-9;
            assert length(session_events where (each["event"] = "arrival")) = 1;
            assert length(session_events where (each["event"] = "service_completed")) = 1;
        }
        if cycle = 1440 {
            assert abs(time - 86400.0) < 1e-9;
            assert abs(simulation_hour - 24.0) < 1e-9;
            write "COARSE_STEP_REGRESSION_PASS";
        }
    }
}
experiment "coarse_step" type: gui { float seed <- 42.0; }
