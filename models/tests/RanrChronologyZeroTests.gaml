model ranr_chronology_zero_tests
import "../ranr/Runtime.gaml"

global {
    geometry shape <- rectangle(100,100);
    float step <- 60.0;
    string fixture_mode <- "zero_front";
    string fixture_events <- "";
    string fixture_output <- "";
    map<string,unknown> expected_schedule <- [];
    list<float> fixture_energies <- [];
    float fixture_initial_delivered <- 0.0;
    init {
        ranr_done <- true;
        create charging_station with:[location::{0,0},port_60::1,ranr_station_limit_kw::60.0];
        ranr_stations <- list(charging_station);
        if fixture_mode="clock_guard" {
            ask charging_station[0] { do ranr_advance_service(1.0); do ranr_advance_service(0.5); }
            write "CLOCK_GUARD_DID_NOT_REJECT"; assert false;
        }
        if fixture_mode in ["outage_sorted","outage_unsorted","tied_restore","tied_shutdown"] {
            ranr_station_events_file <- fixture_events;
            do ranr_load_outage_schedule;
            assert length(ranr_outage_schedule)=2;
            assert float(ranr_outage_schedule[0]["at"])<=float(ranr_outage_schedule[1]["at"]);
            if fixture_mode in ["tied_restore","tied_shutdown"] {
                assert int(ranr_outage_schedule[0]["ordinal"])=0;
                assert int(ranr_outage_schedule[1]["ordinal"])=1;
            }
            fixture_energies <- [9.0];
        } else {
            fixture_energies <- fixture_mode="zero_middle" ? [1.0,0.0,1.0] :
                (fixture_mode="all_zero" ? [0.0,0.0] :
                 (fixture_mode="tiny_front" ? [1e-12,1.0] :
                  (fixture_mode="tiny_last" ? [1.0,1e-12] : [0.0,1.0])));
            list<map<string,unknown>> jobs <- [];
            loop i from:0 to:length(fixture_energies)-1 {
                map<string,unknown> job <- ranr_record(["at"::0.0,"energy"::fixture_energies[i],"max_kw"::60.0,"soc"::30.0]);
                if fixture_mode="zero_busy" and i=0 { job["port"] <- 0; }
                jobs << job;
            }
            expected_schedule <- ranr_service_schedule([60.0],jobs,60.0,10.0);
            assert bool(expected_schedule["cleared"]);
            assert empty(list<float>(expected_schedule["starts"]) where (each<0.0));
            loop i from:0 to:length(fixture_energies)-1 {
                float expected <- fixture_energies[i];
                assert abs(list<float>(expected_schedule["delivered"])[i]-expected)<=max(1e-18,abs(expected)*1e-12);
                assert list<float>(expected_schedule["finishes"])[i]>=list<float>(expected_schedule["starts"])[i];
            }
        }
        loop i from:0 to:length(fixture_energies)-1 {
            float energy <- fixture_energies[i];
            if fixture_mode="zero_busy" and i=0 { energy <- 1.0; }
            create chronology_zero_ev with:[location::{0,0},battery_level::30.0,requested_energy::energy] {
                ranr_demand_key <- i+1; ranr_max_kw <- 60.0;
                do begin_request; current_station <- charging_station[0]; do start_charging;
                if fixture_mode="zero_busy" and i=0 {
                    // Seed an already delivered owner, still awaiting its terminal dispatch.
                    delivered_energy <- 1.0; ranr_lifetime_charged_kwh <- 1.0;
                    battery_level <- battery_level+100.0/battery_capacity_kwh;
                    charging_station[0].power_consumed <- 1.0/charge_efficiency;
                    fixture_initial_delivered <- 1.0;
                    ask charging_station[0] { do process_queue; }
                }
            }
        }
    }
    reflex check {
        float at <- time/60.0;
        do ranr_apply_outages(at);
        ask charging_station { do ranr_advance_service(at); do process_queue; }
        assert charging_station[0].ranr_service_clock=at;
        assert charging_station[0].installed_port_count=1;
        assert charging_station[0].port_60+length(charging_station[0].charging_vehicles)=1;
        if cycle=5 {
            if fixture_mode in ["outage_sorted","outage_unsorted","tied_restore","tied_shutdown"] {
                float expected <- fixture_mode="tied_restore" ? 4.5 : (fixture_mode="tied_shutdown" ? 0.45 : 0.72);
                assert abs(chronology_zero_ev[0].delivered_energy-expected)<1e-9;
                float before <- chronology_zero_ev[0].delivered_energy;
                do ranr_apply_outages(at);
                assert chronology_zero_ev[0].delivered_energy=before;
            } else {
                assert empty(charging_station[0].charging_vehicles);
                assert empty(charging_station[0].waiting_queue);
                assert empty(charging_station[0].physical_sessions);
                loop i from:0 to:length(fixture_energies)-1 {
                    chronology_zero_ev ev <- chronology_zero_ev[i];
                    assert ev.session_state="completed" and !ev.needs_charging and !ev.is_charging;
                    assert ev.current_station=nil;
                    assert abs(ev.service_start-list<float>(expected_schedule["starts"])[i])<1e-9;
                    assert abs(ev.service_finish-list<float>(expected_schedule["finishes"])[i])<1e-9;
                    float expected <- fixture_mode="zero_busy" and i=0 ? 1.0 : fixture_energies[i];
                    assert abs(ev.delivered_energy-expected)<=max(1e-18,abs(expected)*1e-12);
                    if fixture_energies[i]>0.0 { assert ev.delivered_energy>0.0; }
                    assert abs(ev.battery_level-(30.0+100.0*expected/battery_capacity_kwh))<1e-9;
                }
                assert abs(charging_station[0].power_consumed-(sum(fixture_energies)+fixture_initial_delivered)/charge_efficiency)<1e-9;
            }
            if fixture_output!="" {
                save ["mode"::fixture_mode,"delivered"::(chronology_zero_ev collect each.delivered_energy),
                    "starts"::(chronology_zero_ev collect each.service_start),"finishes"::(chronology_zero_ev collect each.service_finish),
                    "port_available"::charging_station[0].port_60,"owners"::length(charging_station[0].charging_vehicles),
                    "expected_schedule"::expected_schedule] to:fixture_output format:"json";
            }
            write "RANR_CHRONOLOGY_ZERO_PASS "+fixture_mode;
        }
    }
}
species chronology_zero_ev parent:elecar;
experiment "ranr_chronology_zero" type:gui {
    parameter "Mode" var:fixture_mode;
    parameter "Events" var:fixture_events;
    parameter "Output" var:fixture_output;
}
