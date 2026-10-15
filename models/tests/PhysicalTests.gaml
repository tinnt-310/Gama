model physical_tests
import "../Traffic.gaml"

global {
    geometry shape <- rectangle(1000, 1000);
    float test_start;
    init {
        create intersection with: [location::{100,100}];
        create building with: [location::{100,100}, build_type::1];
        buildings_type_1 <- list(building);
        buildings_type_2 <- list(building);
        buildings_type_3 <- list(building);
        create charging_station with: [port_60::1, location::{100,100}];
        create private_ev number: 3 with: [location::{100,100}, home::building[0], battery_level::79.0];
        loop ev over: private_ev {
            ask ev {
                current_station <- charging_station[0];
                needs_charging <- true;
                do start_charging;
            }
        }
        test_start <- simulation_hour;
    }
    reflex verify {
        assert length(charging_station[0].charging_vehicles) <= 1;
        assert empty(charging_station[0].charging_vehicles inter charging_station[0].waiting_queue);
        if cycle = 5 {
            ask private_ev[1] { do start_charging; do start_charging; }
            assert charging_station[0].arrived_customer = 3;
            assert private_ev[1].waiting_time > 0.0;
            assert abs((simulation_hour - test_start) * 3600 - 5.0) < 1.01;
        }
        if cycle = 145 {
            create private_ev with: [location::{100,100},home::building[0],battery_level::79.0] {
                current_station <- charging_station[0];
                do start_charging;
                do cancel_request("cancelled");
                do cancel_request("cancelled");
            }
            assert charging_station[0].port_60 = 1;
            assert empty(charging_station[0].charging_vehicles);
            assert length(session_events where (each["event"] = "cancelled")) = 1;
        }
        if cycle = 200 {
            assert charging_station[0].served_customer = 3;
            assert empty(charging_station[0].waiting_queue);
            assert charging_station[0].port_60 = 1;
            assert abs(charging_station[0].power_consumed - 2.0) < 1e-9;
            assert abs(private_ev[0].delivered_energy - 0.6) < 1e-9;
            assert length(session_events where (each["event"] = "service_completed")) = 3;
            write "PHYSICAL_TESTS_PASS";
        }
    }
}
experiment "physical" type: gui {
    float seed <- 42.0;
}
