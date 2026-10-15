model fixed_port_forecast_tests
import "../Traffic.gaml"

global {
    geometry shape <- rectangle(1000,1000);
    init {
        create intersection with: [location::{100,100}];
        create building with: [location::{100,100},closest_intersection::intersection[0],build_type::1];
        buildings_type_1 <- list(building); buildings_type_2 <- list(building); buildings_type_3 <- list(building);
        create charging_station with: [location::{100,100},closest_intersection::intersection[0],port_60::1];
        create private_ev number: 2 with: [location::{100,100},home::building[0],battery_level::78.5] {
            do begin_request;
            assert abs(workload-1.0) < 1e-9;
            current_station <- charging_station[0]; do start_charging;
        }
        charging_station station <- charging_station[0];
        elecar busy <- private_ev[0];
        assert length(station.waiting_queue) = 1 and station.port_60 = 0;
        string before <- string([station.physical_sessions,station.waiting_queue,station.charging_vehicles,
            station.port_60,busy.battery_level,busy.delivered_energy,session_events,seed]);
        list<float> early <- station.forecast_fixed_port(0.0,2,5.0);
        assert abs(early[0]-3.0) < 1e-9 and abs(early[1]-5.0) < 1e-9;
        assert before = string([station.physical_sessions,station.waiting_queue,station.charging_vehicles,
            station.port_60,busy.battery_level,busy.delivered_energy,session_events,seed]);
        busy.requested_energy <- 5.4;
        list<float> late <- station.forecast_fixed_port(0.0,2,5.0);
        assert abs(late[0]) < 1e-9 and abs(late[1]-3.0) < 1e-9;
        assert length(station.waiting_queue) = 1;
        station.inbound_work["future"] <- 1000.0; station.inbound_eta["future"] <- 20.0;
        assert station.forecast_fixed_port(0.0,2,5.0) = late;
        busy.completion_pending <- true; busy.service_finish <- 0.5;
        list<float> pending <- station.forecast_fixed_port(0.0,2,5.0);
        assert abs(pending[0]-3.5) < 1e-9;
        step <- 60.0;
        pending <- station.forecast_fixed_port(0.0,2,5.0);
        assert abs(pending[0]-3.0) < 1e-9; // release at minute 1, queued job ends at minute 2
        step <- 1.0;
        busy.completion_pending <- false; busy.service_finish <- -1.0; busy.requested_energy <- 0.9;
        ask busy { do cancel_request("cancelled"); }
        assert abs(station.forecast_fixed_port(0.0,2,5.0)[0]-4.0) < 1e-9;
        ask private_ev[1] { do start_charging; do start_charging; }
        assert station.arrived_customer = 2;
        assert !(private_ev[1].request_id in station.inbound_work.keys);
        ask private_ev[1] { do cancel_request("cancelled"); }
        assert station.port_60 = 1 and station.forecast_fixed_port(0.0,2,5.0) = [5.0,5.0];
        create charging_station with: [port_60::1,port_30::1];
        assert charging_station[1].forecast_fixed_port(0.0,2,5.0) = [7.5,7.5];
        create charging_station;
        assert charging_station[2].forecast_fixed_port(0.0,2,5.0) = [0.0,0.0];
        charge_efficiency <- 0.45;
        assert charging_station[1].forecast_fixed_port(0.0,2,5.0) = [3.75,3.75];
        create private_ev with: [location::{100,100},home::building[0],battery_level::78.5] {
            do begin_request; assert abs(workload-1.0) < 1e-9;
        }
        charge_efficiency <- 0.9;
        create charging_station with: [location::{100,100},port_60::1,port_30::1];
        create private_ev number: 3 with: [location::{100,100},home::building[0],battery_level::78.5] {
            do begin_request; current_station <- charging_station[3]; do start_charging;
        }
        assert length(charging_station[3].waiting_queue) = 1;
        assert charging_station[3].forecast_fixed_port(0.0,2,5.0) = [4.5,7.5];
        write "FORECAST_CAPACITY_PAIR " + [early,late];
        write "FIXED_PORT_FORECAST_TESTS_PASS";
    }
}
experiment "forecast" type: gui { float seed <- 42.0; }
