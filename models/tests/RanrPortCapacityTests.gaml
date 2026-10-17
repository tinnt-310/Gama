model ranr_port_capacity_tests
import "../ChargingService.gaml"
global {
    geometry shape <- rectangle(100,100);
    float step <- 60.0;
    bool ranr_enabled <- true;
    float ranr_deadline <- 360.0;
    init {
        loop sid from:0 to:5 {
            create charging_station with:[location::{0,0},port_60::(sid mod 2=0 ? 10 : 20),ranr_sid::sid,ranr_station_limit_kw::(sid>=4 ? 60.0 : -1.0)];
            charging_station station <- charging_station[sid];
            create capacity_ev number:(sid=2 or sid=3 ? 21 : 4) with:[location::{0,0},battery_level::30.0,requested_energy::9.0] {
                fixture_sid <- sid; ranr_demand_key <- index+1; ranr_max_kw <- 60.0;
                do begin_request; current_station <- station; do start_charging;
            }
        }
        assert length(charging_station[0].charging_vehicles)=4 and empty(charging_station[0].waiting_queue);
        assert length(charging_station[1].charging_vehicles)=4 and empty(charging_station[1].waiting_queue);
        assert length(charging_station[2].waiting_queue)=11 and length(charging_station[3].waiting_queue)=1;
    }
    reflex advance {
        ask charging_station { do ranr_advance_service(time/60.0); do process_queue; }
        if cycle=1 {
            loop sid over:[4,5] {
                list<capacity_ev> group <- list(capacity_ev) where (each.fixture_sid=sid);
                assert abs(sum(group collect each.delivered_energy)-charge_efficiency)<1e-7;
            }
        }
        if cycle=60 {
            assert empty(list(capacity_ev) where (each.session_state!="completed"));
            assert max(list(capacity_ev) where (each.fixture_sid=2) collect each.waiting_time)>
                   max(list(capacity_ev) where (each.fixture_sid=3) collect each.waiting_time);
            loop sid from:0 to:5 {
                charging_station station <- charging_station[sid];
                list<capacity_ev> group <- list(capacity_ev) where (each.fixture_sid=sid);
                assert abs(sum(group collect each.delivered_energy)-9.0*length(group))<1e-7;
                assert abs(station.power_consumed*charge_efficiency-9.0*length(group))<1e-7;
                assert station.installed_port_count=(sid mod 2=0 ? 10 : 20);
                assert empty(station.charging_vehicles) and empty(station.waiting_queue);
            }
            write "RANR_PORT_CAPACITY_PASS";
        }
    }
}
species capacity_ev parent:elecar { int fixture_sid <- -1; }
experiment "ranr_port_capacity" type:gui;
