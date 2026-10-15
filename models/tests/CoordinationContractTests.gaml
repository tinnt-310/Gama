model coordination_contract_tests
import "../Coordination.gaml"

global {
    geometry shape <- rectangle(2000,2000);
    bool coordination_enabled <- false;
    float ele_car_speed <- 36.0;
    init {
        run_prefix <- "../../outputs/review_contract";
        create intersection with: [location::{100,100}];
        create intersection with: [location::{700,100}];
        create intersection with: [location::{100,1300}];
        create road with: [shape::polyline([intersection[0].location,intersection[1].location]),num_lanes::2];
        create road with: [shape::polyline([intersection[0].location,intersection[2].location]),num_lanes::2];
        create road with: [shape::polyline([{700,100},{700,1300},{100,1300}]),num_lanes::2];
        road_network <- as_driving_graph(road,intersection) with_shortest_path_algorithm "Dijkstra";
        road[0].speed_coeff <- 0.25; road[1].speed_coeff <- 1.0; road[2].speed_coeff <- 0.5;
        create building with: [location::intersection[0].location,closest_intersection::intersection[0],build_type::1];
        buildings_type_1 <- list(building); buildings_type_2 <- list(building); buildings_type_3 <- list(building);
        create charging_station number: 2 {
            closest_intersection <- intersection[index+1]; location <- closest_intersection.location; port_60 <- 1;
        }
        create private_ev with: [location::intersection[0].location,home::building[0],battery_level::79.0] { do begin_request; }
        elecar ev <- private_ev[0];
        epoch_min <- 0.0;
        do build_candidates(ev);
        assert ev.candidates[0] = charging_station[1]; // Farther but faster at this road-speed snapshot.
        assert ev.nearest_candidate = charging_station[0];
        assert abs(ev.candidate_eta[0]-2.0) < 1e-8 and abs(ev.candidate_eta[1]-4.0) < 1e-8;
        eta_model <- "nominal_speed"; do build_candidates(ev);
        assert ev.candidates[0] = charging_station[0] and abs(ev.candidate_eta[0]-1.0) < 1e-8;
        eta_model <- "snapshot_speed"; assignment_policy <- "nearest";
        do coordinate_batch;
        assert ev.current_station = charging_station[0] and abs(ev.assigned_eta-4.0) < 1e-8;
        int calls_before <- event_write_calls;
        do export_run; do export_run;
        assert exported_event_count = 3 and event_write_calls = calls_before;
        // Keep a committed route even after a shorter road is added to the graph.
        road_network <- as_driving_graph([road[0],road[2]],intersection) with_shortest_path_algorithm "Dijkstra";
        create private_ev with: [location::intersection[0].location,home::building[0],battery_level::79.0] {
            do begin_request; current_station <- charging_station[1]; session_state <- "en_route";
            do compute_path graph: road_network target: current_station.closest_intersection;
        }
        elecar inbound <- private_ev[1];
        list<float> committed <- route_forecast(inbound,charging_station[1]);
        assert abs(committed[0]-2400.0) < 1e-8;
        create road with: [shape::polyline([intersection[1].location,intersection[2].location]),num_lanes::2];
        road_network <- as_driving_graph(road,intersection) with_shortest_path_algorithm "Dijkstra";
        assert abs(route_forecast(inbound,charging_station[1])[0]-committed[0]) < 1e-8;
        ask inbound { do cancel_request("cancelled"); }
        do export_run; do export_run;
        assert exported_event_count = 5 and event_write_calls = calls_before+1;
        write "COORDINATION_CONTRACT_TESTS_PASS";
    }
}
experiment "contract" type: gui { float seed <- 42.0; }
