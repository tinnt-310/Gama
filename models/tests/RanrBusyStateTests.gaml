model ranr_busy_state_tests
import "../ChargingService.gaml"
global {
    geometry shape <- rectangle(100,100);
    float step <- 60.0;
    string fixture_mode <- "sharing";
    float predicted_wait <- -1.0;
    init {
        if fixture_mode="taper" { ranr_taper_soc <- [0.0,80.0,100.0]; ranr_taper_factors <- [1.0,0.5,0.5]; }
        create charging_station with:[location::{0,0},port_60::(fixture_mode="heterogeneous" ? 1 : 2),
            port_250::(fixture_mode="heterogeneous" ? 1 : 0),ranr_station_limit_kw::(fixture_mode="caps" ? 120.0 : 60.0)];
        create busy_state_ev number:2 with:[location::{0,0},battery_level::(fixture_mode="taper" ? 85.0 : 30.0),requested_energy::9.0] {
            ranr_demand_key <- index+1; ranr_max_kw <- index=0 ? 10.0 : 60.0;
            do begin_request; current_station <- charging_station[0]; do start_charging;
        }
        ask charging_station[0] {
            if fixture_mode="outage" { ranr_failed_ports <- [0]; }
            do ranr_capture(0.0);
        }
        map<string,unknown> snapshot <- charging_station[0].ranr_local_snapshot;
        assert length(list(snapshot["busy"]))=2;
        map<string,unknown> cloned <- ranr_clone_snapshot(snapshot);
        list<map<string,unknown>> cloned_jobs <- cloned["busy"];
        cloned_jobs[0]["energy"] <- 123.0;
        assert list<map<string,unknown>>(snapshot["busy"])[0]["energy"]=9.0;
        map<string,unknown> shadow <- ranr_shadow_observed(snapshot,list<float>(snapshot["release_lo"]),
            [["at"::0.0,"energy"::1.0,"max_kw"::60.0,"soc"::30.0]],float(snapshot["aggregate_kw"]));
        predicted_wait <- list<float>(shadow["waits"])[0];
        create busy_state_ev with:[location::{0,0},battery_level::30.0,requested_energy::1.0] {
            ranr_demand_key <- 3; ranr_max_kw <- 60.0;
            do begin_request; current_station <- charging_station[0]; do start_charging;
        }
    }
    reflex advance {
        ask charging_station { do ranr_advance_service(time/60.0); do process_queue; }
        if cycle=200 {
            assert busy_state_ev[2].session_state="completed";
            assert abs(predicted_wait-busy_state_ev[2].waiting_time)<1e-7;
            assert abs(busy_state_ev[2].delivered_energy-1.0)<1e-7;
            write "RANR_BUSY_STATE_PASS "+fixture_mode+" shadow="+predicted_wait+" physical="+busy_state_ev[2].waiting_time;
        }
    }
}
species busy_state_ev parent:elecar;
experiment "ranr_busy_state" type:gui {
    parameter "Busy state fixture mode" var:fixture_mode;
}
