model waiting_prediction_tests
import "../Recommendation.gaml"
global {
    geometry shape <- rectangle(1000,1000);
    bool coordination_enabled <- false;
    string waiting_forecast_mode <- "B3";
    float recorded_prediction <- -1.0;
    init {
        create intersection with: [location::{100,100}];
        create building with: [location::{100,100},closest_intersection::intersection[0],build_type::1];
        buildings_type_1 <- list(building); buildings_type_2 <- list(building); buildings_type_3 <- list(building);
        create charging_station number: 2 with: [location::{100,100},closest_intersection::intersection[0],port_60::1];
        create private_ev number: 2 with: [location::{100,100},home::building[0],battery_level::79.0] {
            do begin_request; requested_energy <- index = 0 ? 9.0 : 0.9;
            current_station <- charging_station[index]; commit_time <- 0.0; do start_charging;
        }
        charging_station busy <- charging_station[0]; charging_station fast <- charging_station[1];
        assert length(busy.waiting_queue) = length(fast.waiting_queue);
        string original <- string([busy.physical_sessions,busy.port_60,private_ev[0].battery_level,session_events,seed]);
        recorded_prediction <- float(busy.predict_waiting(0.0,2.0)["waiting"]);
        assert abs(recorded_prediction-8.0) < 1e-9;
        assert float(fast.predict_waiting(0.0,2.0)["waiting"]) = 0.0;
        assert original = string([busy.physical_sessions,busy.port_60,private_ev[0].battery_level,session_events,seed]);
    }
    reflex arrival_probe when: cycle = 120 {
        create private_ev with: [location::{100,100},home::building[0],battery_level::79.0] {
            do begin_request; current_station <- charging_station[0]; commit_time <- time/60.0; do start_charging; do start_charging;
        }
        assert charging_station[0].arrived_customer = 2;
    }
    reflex verify_wait_prediction when: cycle = 602 {
        elecar probe <- private_ev[2];
        assert probe.service_start >= 0.0;
        assert abs(probe.waiting_time-recorded_prediction) <= step/60.0+1e-9;
        assert charging_station[0].arrived_customer = 2;
        assert abs(probe.waiting_time-(probe.service_start-probe.arrival_time)) < 1e-9;
        write "WAITING_PREDICTION_PHYSICAL_PASS " + [recorded_prediction,probe.waiting_time];
    }
}
experiment "waiting_tests" type: gui { float seed <- 42.0; }
