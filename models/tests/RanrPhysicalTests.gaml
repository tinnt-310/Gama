model ranr_physical_tests
import "../ChargingService.gaml"
global {
    geometry shape <- rectangle(100,100);
    float step <- 60.0;
    bool ranr_enabled <- true;
    float ranr_deadline <- 360.0;
    init {
        create charging_station with: [location::{0,0},port_250::1];
        create ranr_test_ev number:2 with: [location::{0,0},battery_level::30.0,requested_energy::9.0] {
            ranr_demand_key <- index+1;ranr_max_kw <- index=0 ? 120.0 : 60.0;
            do begin_request;current_station <- charging_station[0];do start_charging;
        }
        assert ranr_test_ev[0].charge_rate=120 and ranr_test_ev[0].charge_port_rate=250;
        assert ranr_test_ev[1].session_state="waiting" and length(charging_station[0].waiting_queue)=1;
        assert ranr_test_ev[0].delivered_energy=0.0;
    }
    reflex advance {
        ask charging_station { do ranr_advance_service(time/60.0); do process_queue; }
        assert charging_station[0].installed_port_count=1;
        if cycle=5 {
            assert ranr_test_ev[0].session_state="completed";
            assert abs(ranr_test_ev[0].delivered_energy-9.0)<1e-9;
            assert ranr_test_ev[1].session_state="charging" and ranr_test_ev[1].waiting_time=5.0;
        }
        if cycle=15 {
            assert ranr_test_ev[1].session_state="completed";
            assert charging_station[0].port_250=1 and empty(charging_station[0].charging_vehicles);
            assert abs(charging_station[0].power_consumed-20.0)<1e-9;
            assert length(session_events where (each["event"]="service_completed"))=2;
            write "RANR_PHYSICAL_PASS";
        }
    }
}
species ranr_test_ev parent:elecar;
experiment "ranr_physical" type:gui;
