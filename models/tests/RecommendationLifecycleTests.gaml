model recommendation_lifecycle_tests
import "../Recommendation.gaml"
global {
    geometry shape <- rectangle(2000,1000);
    bool coordination_enabled <- false;
    string runtime_mode <- "RECOMMENDATION_RUNTIME";
    string oracle_backend <- "fixed_port";
    string run_prefix <- "../../outputs/recommendation_validation/lifecycle";
    init {
        create intersection number: 3 { location <- {100.0+index*300.0,100}; }
        loop k from: 0 to: 1 {
            create road with: [shape::polyline([intersection[k].location,intersection[k+1].location]),num_lanes::2];
            create road with: [shape::polyline([intersection[k+1].location,intersection[k].location]),num_lanes::2];
        }
        road_network <- as_driving_graph(road,intersection) with_shortest_path_algorithm "Dijkstra";
        create building with: [location::intersection[0].location,closest_intersection::intersection[0],build_type::1];
        buildings_type_1 <- list(building); buildings_type_2 <- list(building); buildings_type_3 <- list(building);
        create charging_station number: 2 { name <- index = 0 ? "near" : "far"; closest_intersection <- intersection[index+1]; location <- closest_intersection.location; port_60 <- 1; }
        save "request_id,time_min,station\nreq_1,0.0,far\n" to: "../../outputs/recommendation_validation/choice_trace.csv" format: "text";
        exogenous_choice_trace_file <- "../../outputs/recommendation_validation/choice_trace.csv";
        ev_choice_mode <- "EXOGENOUS_CHOICE_TRACE";
        publish_intention <- true;
        do initialize_recommendation;
        create private_ev with: [location::intersection[0].location,home::building[0],battery_level::35.0] { do begin_request; }
        elecar ev <- private_ev[0]; epoch_min <- 0.0;
        do generate_recommendation(ev); do execute_ev_choice(ev);
        assert ev.recommended_station = charging_station[0] and ev.actual_chosen_station = charging_station[1];
        assert ev.request_id in charging_station[1].intention_records.keys;
        assert ev.request_id in pending_session_data.keys;
        assert empty(charging_station[1].inbound_work) and empty(charging_station[1].physical_sessions);
        ask ev { do unregister; do die; }
    }
    reflex verify_external_removal when: cycle = 1 {
        assert length(session_events where (each["event"] = "cancelled")) = 1;
        assert empty(charging_station[1].intention_records) and empty(pending_session_data);
        assert empty(charging_station[1].inbound_work) and charging_station[1].arrived_customer = 0;
        write "RECOMMENDATION_LIFECYCLE_PASS";
    }
}
experiment "lifecycle_tests" type: gui { float seed <- 42.0; }
