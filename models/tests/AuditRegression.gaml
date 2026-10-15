model audit_regression
import "../Coordination.gaml"

global {
    geometry shape <- rectangle(1000,1000);
    init {
        coordination_enabled <- false;
        create intersection with: [location::{100,100}];
        create building with: [location::{100,100},closest_intersection::intersection[0],build_type::1];
        buildings_type_1 <- list(building); buildings_type_2 <- list(building); buildings_type_3 <- list(building);
        create charging_station with: [location::{100,100},closest_intersection::intersection[0],port_60::1];
        charge_efficiency <- 0.5;
        reference_efficiency <- 0.5;
        create private_ev with: [location::{100,100},home::building[0],battery_level::79.0] { do begin_request; }
        // 0.6 kWh / (0.5 * 60 kW) = 1.2 reference service minutes.
        assert abs(private_ev[0].workload - 1.2) < 1e-10;
        ask private_ev[0] {
            current_station <- charging_station[0];
            do cancel_request("cancelled");
            current_station <- charging_station[0];
            do start_charging;
        }
        assert private_ev[0].session_state = "cancelled";
        assert charging_station[0].arrived_customer = 0;
        assert charging_station[0].port_60 = 1;
        // A request can disappear before assignment, without ever entering a station ledger.
        create private_ev with: [location::{100,100},home::building[0],battery_level::79.0] {
            do begin_request;
            do die;
        }
        create private_ev with: [location::{100,100},home::building[0],battery_level::79.0] {
            do cancel_request("stranded");
        }
    }
    reflex verify_pending_cleanup when: cycle = 1 {
        assert length(session_events where (each["event"] = "cancelled")) = 2;
        assert empty(pending_session_data);
        assert empty(session_events where (each["request_id"] = ""));
        write "AUDIT_REGRESSION_PASS";
    }
}
experiment "audit" type: gui { float seed <- 42.0; }
