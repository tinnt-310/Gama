model observation_forecast_tests
import "../Recommendation.gaml"
global {
    geometry shape <- rectangle(1000,1000);
    bool coordination_enabled <- false;
    string runtime_mode <- "RECOMMENDATION_RUNTIME";
    string oracle_backend <- "fixed_port";
    string waiting_forecast_mode <- "B4-N";
    bool neighbor_correction_enabled <- true;
    float replay_similarity_threshold <- 4.0; // Fixture-only threshold, not empirical calibration.
    init {
        create charging_station number: 2 with: [port_60::1];
        charging_station station <- charging_station[0]; charging_station neighbor <- charging_station[1];
        station.information_neighbors <- [neighbor]; neighbor.information_neighbors <- [station];
        loop b from: 0 to: 80 {
            float at <- b*5.0+1.0;
            ask station { do observe_arrival(at,b mod 4 = 0 ? 18.0 : 9.0); }
            ask neighbor { do observe_arrival(at,b mod 4 = 3 ? 18.0 : 9.0); }
        }
        assert abs(station.local_arrival_forecast(5.0)-20.0) < 1e-9;
        assert abs(station.local_arrival_forecast(10.0)-15.0) < 1e-9;
        float before <- station.local_arrival_forecast(10.0);
        ask station { do observe_arrival(10000.0,900000.0); do report_intention("unknown",20.0,90000.0); }
        assert abs(station.local_arrival_forecast(10.0)-before) < 1e-9;
        loop b from: 0 to: 60 {
            float at <- b*5.0;
            ask charging_station { do receive_available_forecasts(at); }
            ask charging_station { do issue_station_forecast(at); }
        }
        map<string,unknown> first_model <- station.correction_models[0];
        map<string,unknown> last_model <- station.correction_models[23];
        assert int(first_model["count"]) = 60;
        assert int(last_model["count"]) = 37;
        assert length(station.communication_events) = 60;
        loop label_data over: station.forecast_evaluations {
            assert float(label_data["observed_at"]) >= float(label_data["issued_at"])+(int(label_data["horizon"])+1)*5.0-1e-9;
        }
        neighbor_delay_minutes <- 15.0;
        ask neighbor { do issue_station_forecast(305.0); }
        int received <- length(station.communication_events);
        ask station { do receive_available_forecasts(310.0); }
        assert length(station.communication_events) = received+1; // Old zero-delay packet at 300.
        ask station { do receive_available_forecasts(320.0); }
        assert float(station.received_forecasts[neighbor.name]["issued_at"]) = 305.0;
        assert float(station.received_forecasts[neighbor.name]["deliver_at"]) = 320.0;
        neighbor_correction_enabled <- false;
        assert station.corrected_arrival(320.0,0,12.0) = 12.0;
        assert empty(station.inbound_work) and empty(station.waiting_queue);
        write "OBSERVATION_FORECAST_TESTS_PASS";
    }
}
experiment "observation_tests" type: gui { float seed <- 42.0; }
