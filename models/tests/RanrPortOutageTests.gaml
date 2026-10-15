model ranr_port_outage_tests
import "../ChargingService.gaml"
global {
    geometry shape <- rectangle(100,100);
    float step <- 60.0;
    init {
        create charging_station with:[location::{0,0},port_250::1];
        create outage_probe with:[location::{0,0},battery_level::29.0,requested_energy::9.0] {
            ranr_demand_key <- 1; ranr_max_kw <- 120.0; do begin_request;
            current_station <- charging_station[0]; do start_charging;
        }
    }
    reflex update {
        ask charging_station { do ranr_advance_service(time/60.0); }
        if cycle=1 { charging_station[0].ranr_failed_ports <- [0]; }
        if cycle=2 { assert abs(outage_probe[0].delivered_energy-1.8)<1e-9; }
        if cycle=3 { charging_station[0].ranr_failed_ports <- []; }
        assert charging_station[0].installed_port_count=1;
        if cycle=7 {
            assert outage_probe[0].session_state="completed";
            assert abs(outage_probe[0].delivered_energy-9.0)<1e-9;
            assert abs(outage_probe[0].ranr_charge_elapsed-7.0)<1e-9;
            assert abs(outage_probe[0].charging_time-5.0)<1e-9;
            assert abs(charging_station[0].power_consumed-10.0)<1e-9;
            assert length(outage_probe)=1;
            charging_station[0].ranr_capacity_factor <- 0.33;
            create outage_probe with:[location::{0,0},battery_level::29.0,requested_energy::9.0] {
                ranr_demand_key <- 2; ranr_max_kw <- 120.0; do begin_request; current_station <- charging_station[0]; do start_charging;
            }
            assert abs(outage_probe[1].charge_rate-82.5)<1e-9;
            write "RANR_PORT_OUTAGE_PASS";
        }
    }
}
species outage_probe parent:elecar;
experiment "ranr_port_outage" type:gui;
