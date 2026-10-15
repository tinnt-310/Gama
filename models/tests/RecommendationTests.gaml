model recommendation_tests
import "../Recommendation.gaml"

global {
    geometry shape <- rectangle(2000,1000);
    bool coordination_enabled <- false;
    string runtime_mode <- "RECOMMENDATION_RUNTIME";
    string oracle_backend <- "fixed_port";
    float ele_car_speed <- 36.0;
    string run_prefix <- "../../outputs/recommendation_validation/contracts";
    init {
        list<float> no_weights <- [];
        list<map> options <- [
            ["sid"::0,"criteria"::[20.0,3.0,0.6,10.0]],
            ["sid"::1,"criteria"::[10.0,9.0,1.8,3.0]],
            ["sid"::2,"criteria"::[14.0,6.0,1.2,6.0]]];
        list<map> ranking <- rank_station_options(options,"feasible","minimax",no_weights);
        assert int(first(ranking where bool(each["recommended"]))["sid"]) = 2;
        assert abs(float(ranking[2]["score"])-0.5) < 1e-10;
        assert int(ranking[2]["alternative_rank"]) = 1 and string(ranking[2]["score_method"]) = "minimax";
        assert empty(rank_station_options([],"feasible","minimax",no_weights));
        assert discrete_shadow_wait([60.0],[0.0],[["offset"::1.0,"energy"::0.9],["offset"::1.0,"energy"::0.9]],1.0) = 2.0;
        assert discrete_shadow_wait([60.0],[10.0],[],3.0) = 7.0;
        assert discrete_shadow_wait([11.0,60.0],[0.0,1.0],[["offset"::2.0,"energy"::0.9],["offset"::2.0,"energy"::0.99]],2.0) = 1.0;
        assert discrete_shadow_wait([11.0,60.0],[0.0,1.0],[["offset"::2.0,"energy"::0.9],["offset"::2.0,"energy"::0.99]],3.0) = 0.0;
        list<float> coupled_weights <- ridge_solution([4.0,1.0,1.0,3.0],[1.0,2.0]);
        assert abs(coupled_weights[0]-1.0/11.0) < 1e-10 and abs(coupled_weights[1]-7.0/11.0) < 1e-10;
        list<float> weights <- ridge_solution([2.0,0.0,0.0,4.0],[4.0,8.0]); assert weights = [2.0,2.0];

        create intersection number: 3 { location <- {100.0+index*300.0,100}; }
        loop k from: 0 to: 1 {
            create road with: [shape::polyline([intersection[k].location,intersection[k+1].location]),num_lanes::2];
            create road with: [shape::polyline([intersection[k+1].location,intersection[k].location]),num_lanes::2];
        }
        road_network <- as_driving_graph(road,intersection) with_shortest_path_algorithm "Dijkstra";
        create building with: [location::intersection[0].location,closest_intersection::intersection[0],build_type::1];
        buildings_type_1 <- list(building); buildings_type_2 <- list(building); buildings_type_3 <- list(building);
        create charging_station number: 2 { name <- index = 0 ? "near" : "far"; closest_intersection <- intersection[index+1]; location <- closest_intersection.location; port_60 <- 1; }
        create private_ev with: [location::intersection[1].location,home::building[0],battery_level::35.0] {
            do begin_request; current_station <- charging_station[0]; commit_time <- 0.0; do start_charging;
        }
        create private_ev with: [location::intersection[0].location,home::building[0],battery_level::35.0] { do begin_request; }
        elecar ev <- private_ev[1];
        epoch_min <- 0.0;
        do initialize_recommendation;
        do generate_recommendation(ev);
        assert ev.current_station = nil and ev.final_target = nil and ev.session_state = "requested";
        assert !empty(ev.recommendation_result) and ev.recommended_station = charging_station[1];
        assert empty(charging_station[0].inbound_work) and empty(charging_station[1].inbound_work);
        assert charging_station[0].arrived_customer = 1 and charging_station[1].arrived_customer = 0;
        ev_choice_mode <- "DEFER_CHOICE"; do execute_ev_choice(ev); assert ev.current_station = nil;
        ev_choice_mode <- "SELF_INTERESTED_CHOICE"; ev.personal_choice_method <- "nearest";
        do execute_ev_choice(ev);
        assert ev.actual_chosen_station = charging_station[0] and !ev.recommendation_followed;
        assert empty(charging_station[0].inbound_work);
        ask ev { do cancel_request("cancelled"); }

        // Identical requests see the same pre-choice physical state, rather than hidden commitments.
        create private_ev number: 100 with: [location::intersection[0].location,home::building[0],battery_level::35.0] { do begin_request; }
        ev_choice_mode <- "DEFER_CHOICE";
        loop item over: ev_population where (each.session_state = "requested") { do generate_recommendation(item); }
        assert length(ev_population where (each.recommended_station = charging_station[1])) = 101;
        assert charging_station[1].arrived_customer = 0 and empty(charging_station[1].inbound_work);

        // Replay keeps sessions, rejects OOD, never reads future observations.
        charging_station station <- charging_station[1];
        waiting_forecast_mode <- "B4"; observation_min_bins <- 2; observation_min_sessions <- 2;
        replay_similarity_threshold <- 0.0;
        ask station { do observe_arrival(1.0,9.0); do observe_arrival(6.0,9.0); do observe_arrival(1000.0,900.0); }
        assert station.local_arrival_forecast(10.0) = 10.0;
        map replay <- station.replay_windows(10.0,1);
        assert string(replay["status"]) = "replay";
        list scenarios <- list(replay["scenarios"]); assert length(scenarios) = 2;
        assert float(map(list(scenarios[0])[0])["energy"]) = 9.0;
        replay_similarity_threshold <- -1.0;
        assert string(station.replay_windows(10.0,1)["status"]) = "ood_threshold_not_calibrated";
        // A late burst changes the mean; no historical bin matches it exactly.
        ask station { do observe_arrival(11.0,90.0); }
        replay_similarity_threshold <- 0.0;
        assert string(station.replay_windows(15.0,1)["status"]) = "out_of_distribution";
        map prediction <- station.predict_waiting(15.0,2.0);
        assert string(prediction["status"]) = "out_of_distribution" and float(prediction["waiting"]) = 0.0;
        assert length(station.waiting_queue) = 0 and station.arrived_customer = 0;
        charging_goal <- "target_soc";
        create private_ev with: [location::intersection[0].location,home::building[0],battery_level::5.1] { do begin_request; }
        elecar low <- last(private_ev); do build_candidates(low);
        assert length(low.candidates) = 1 and low.candidates[0] = charging_station[0];
        assert abs(low.candidate_requested_energy[0]-(48.0-(3.06-0.054))) < 1e-9;
        assert abs(low.candidate_workload[0]-60.0*low.candidate_requested_energy[0]/54.0) < 1e-9;
        // A manual arrival at the wrong road access must not materialize.
        low.current_station <- charging_station[1]; ask low { do start_charging; }
        assert low.arrival_time < 0.0 and charging_station[1].arrived_customer = 0;
        low.current_station <- nil;
        do export_recommendations; do export_run;
        write "RECOMMENDATION_CONTRACT_PASS";
    }
}
experiment "recommendation" type: gui { float seed <- 42.0; }
