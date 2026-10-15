model end_to_end_tests
import "../Coordination.gaml"

global {
    geometry shape <- rectangle(1000,1000);
    bool tested_memory <- false;
    init {
        run_prefix <- "../../outputs/end_to_end";
        create intersection number: 3 { location <- {100+index*200,100}; }
        create road with: [shape::polyline([intersection[0].location,intersection[1].location]),num_lanes::2];
        create road with: [shape::polyline([intersection[1].location,intersection[2].location]),num_lanes::2];
        create road with: [shape::polyline([intersection[2].location,intersection[1].location]),num_lanes::2];
        create road with: [shape::polyline([intersection[1].location,intersection[0].location]),num_lanes::2];
        road_network <- as_driving_graph(road,intersection) with_shortest_path_algorithm "Dijkstra";
        create building with: [location::intersection[0].location,closest_intersection::intersection[0],build_type::1];
        buildings_type_1 <- list(building);buildings_type_2 <- list(building);buildings_type_3 <- list(building);
        create charging_station number: 2 { location <- intersection[index+1].location; closest_intersection <- intersection[index+1];port_60 <- 1; }
        create private_ev number: 4 with: [location::intersection[0].location,home::building[0],battery_level::79.0] {
            do begin_request;
        }
        do coordinate_batch;
        next_epoch <- 60.0;
        assert sum(list(charging_station) collect sum(each.inbound_work.values)) > 0.0;
        assert length(session_events where (each["event"] = "assigned")) = 4;
        // Cross-batch snapshot includes every unresolved committed request exactly once.
        create private_ev with: [location::intersection[0].location,home::building[0],battery_level::79.0] { do begin_request; }
        do coordinate_batch;
        assert sum(list(assignment_station) collect sum(each.inbound)) > 0.0;
        tested_memory <- true;
        // Battery below reserve yields an empty candidate set, not a runtime error.
        create private_ev with: [location::intersection[0].location,home::building[0],battery_level::1.0] { do begin_request; }
        do coordinate_batch;
        assert last(ev_population).session_state = "deferred";
    }
    reflex verify {
        if cycle = 10 {
            create private_ev with: [location::intersection[0].location,home::building[0],battery_level::79.0] { do begin_request; }
            do coordinate_batch;
            last(ev_population).battery_level <- 0.0;
        }
        if cycle = 100 {
            elecar deferred <- first(ev_population where (each.session_state = "deferred"));
            ask deferred { do cancel_request("cancelled"); }
        }
        loop s over: charging_station {
            assert empty(s.waiting_queue inter s.charging_vehicles);
            assert s.port_60 >= 0 and s.port_60 <= 1;
            loop ev over: s.waiting_queue + s.charging_vehicles { assert !(ev.request_id in s.inbound_work.keys); }
        }
        if cycle = 350 {
            assert tested_memory;
            assert length(session_events where (each["event"] = "request")) = 7;
            assert length(session_events where (each["event"] = "stranded")) = 1;
            assert length(session_events where (each["event"] = "cancelled")) = 1;
            assert sum(list(charging_station) collect each.served_customer) = 5;
            assert sum(list(charging_station) collect length(each.inbound_work)) = 0;
            assert length(session_events where (each["event"] = "arrival")) = 5;
            assert length(session_events where (each["event"] = "service_started")) = 5;
            assert length(session_events where (each["event"] = "service_completed")) = 5;
            assert sum(ev_population collect each.delivered_energy) > 2.99;
            do export_run;
            write "END_TO_END_TESTS_PASS";
        }
    }
}
experiment "end_to_end" type: gui { float seed <- 42.0; }
