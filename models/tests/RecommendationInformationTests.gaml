model recommendation_information_tests
import "../Recommendation.gaml"
global {
    geometry shape <- rectangle(2000,1000);
    bool coordination_enabled <- false;
    string runtime_mode <- "RECOMMENDATION_RUNTIME";
    string oracle_backend <- "fixed_port";
    string information_mode <- "LIMITED_INFORMATION";
    float ele_car_speed <- 36.0;
    string run_prefix <- "../../outputs/recommendation_validation/information";
    init {
        create intersection number: 3 { location <- {100.0+index*300.0,100}; }
        loop k from: 0 to: 1 {
            create road with: [shape::polyline([intersection[k].location,intersection[k+1].location]),num_lanes::2];
            create road with: [shape::polyline([intersection[k+1].location,intersection[k].location]),num_lanes::2];
        }
        road_network <- as_driving_graph(road,intersection) with_shortest_path_algorithm "Dijkstra";
        create building with: [location::intersection[0].location,closest_intersection::intersection[0],build_type::1];
        buildings_type_1 <- list(building); buildings_type_2 <- list(building); buildings_type_3 <- list(building);
        create charging_station number: 2 { closest_intersection <- intersection[index+1]; location <- closest_intersection.location; port_60 <- 1; }
        do initialize_recommendation;
        do update_station_forecasts;
        create private_ev with: [location::intersection[1].location,home::building[0],battery_level::35.0] {
            do begin_request; requested_energy <- 9.0; current_station <- charging_station[0]; do start_charging;
        }
        create private_ev with: [location::intersection[0].location,home::building[0],battery_level::35.0] { do begin_request; }
        elecar ev <- private_ev[1]; epoch_min <- 0.0;
        charging_station[1].advertised_waiting <- [];
        do generate_recommendation(ev);
        assert length(ev.received_station_options) = 1;
        assert abs(float(list(ev.received_station_options[0]["criteria"])[3])-0.5) < 1e-9;
        assert string(ev.received_station_options[0]["forecast_status"]) = "stale_physical_only";
        information_mode <- "LIVE_STATION_INFORMATION";
        do generate_recommendation(ev);
        map near_option <- first(ev.received_station_options where (int(each["sid"]) = charging_station[0].index));
        assert abs(float(list(near_option["criteria"])[3])-9.5) < 1e-9;
        assert ev.recommended_station = charging_station[1];
        assert ev.current_station = nil;
        information_mode <- "LIMITED_INFORMATION";
        charging_station[0].advertised_waiting <- [];
        do generate_recommendation(ev);
        assert string(ev.recommendation_result["status"]) = "unavailable" and empty(ev.received_station_options);
        do execute_ev_choice(ev); assert ev.current_station = nil;
        // Explicit fluid comparator is labelled and separate from discrete waiting.
        waiting_forecast_mode <- "B4"; waiting_estimator_mode <- "fluid";
        ask charging_station[1] { do observe_arrival(1.0,9.0); do observe_arrival(6.0,9.0); }
        map fluid_prediction <- charging_station[1].predict_waiting(10.0,5.0);
        assert string(fluid_prediction["status"]) = "fluid_approximation";
        assert abs(float(fluid_prediction["waiting"])-10.0) < 1e-9;
        do export_recommendations;
        write "RECOMMENDATION_INFORMATION_PASS";
    }
}
experiment "information_tests" type: gui { float seed <- 42.0; }
