model ranr_paired_physical_replay
import "../../models/ChargingService.gaml"
global {
    geometry shape <- rectangle(100,100);
    float step <- 60.0;
    string replay_input <- "";
    string replay_output <- "";
    map<string,unknown> specification <- [];
    list<map<string,unknown>> operations <- [];
    int operation_cursor <- 0;
    bool replay_done <- false;
    map<string,unknown> waits <- [];
    map<string,unknown> statuses <- [];
    int replay_identity <- 0;
    action record_event(elecar ev,string event_type) {
        paired_replay_ev actor <- paired_replay_ev(ev);
        if event_type="service_started" {
            waits[actor.replay_key] <- ev.waiting_time;
            statuses[actor.replay_key] <- "started";
        }
        if event_type="service_completed" {
            assert abs(ev.delivered_energy-ev.requested_energy)<1e-6;
            statuses[actor.replay_key] <- "completed";
        }
        if event_type="abandoned" {
            if !(actor.replay_key in waits.keys) { waits[actor.replay_key] <- ev.waiting_time; }
            statuses[actor.replay_key] <- "cancelled";
        }
    }
    init {
        assert file_exists(replay_input);
        specification <- json_file(replay_input).contents;
        operations <- specification["operations"];
        charge_efficiency <- float(specification["charge_efficiency"]);
        battery_capacity_kwh <- float(specification["battery_capacity_kwh"]);
        ranr_taper_soc <- list<float>(specification["taper_soc"]);
        ranr_taper_factors <- list<float>(specification["taper_factors"]);
        loop item over:list<map<string,unknown>>(specification["stations"]) {
            map<string,unknown> counts <- item["port_counts"];
            create charging_station with:[location::{0,0},ranr_sid::int(item["index"]),
                port_250::int(counts["250"]),port_180::int(counts["180"]),port_150::int(counts["150"]),
                port_60::int(counts["60"]),port_30::int(counts["30"]),port_11::int(counts["11"]),
                ranr_station_limit_kw::float(item["aggregate_kw"])];
        }
    }
    reflex physical_replay when:!replay_done {
        float at <- time/60.0;
        ask charging_station { do ranr_advance_service(at); do process_queue; }
        loop while:operation_cursor<length(operations) and float(operations[operation_cursor]["at"])<=at+1e-9 {
            map<string,unknown> item <- operations[operation_cursor]; operation_cursor <- operation_cursor+1;
            string identity <- string(item["identity"]);
            if item["operation"]="arrival" {
                create paired_replay_ev with:[location::{0,0},battery_level::float(item["soc"]),
                    requested_energy::float(item["energy"]),replay_key::identity] {
                    ranr_demand_key <- world.replay_identity; world.replay_identity <- world.replay_identity+1;
                    ranr_max_kw <- float(item["max_kw"]); do begin_request;
                    current_station <- charging_station[int(item["station_index"])]; do start_charging;
                }
            } else {
                paired_replay_ev actor <- first(paired_replay_ev where (each.replay_key=identity));
                if actor!=nil and actor.needs_charging { ask actor { do cancel_request("abandoned"); } }
            }
        }
        ask paired_replay_ev where (each.session_state in ["completed","abandoned"]) { do die; }
        if operation_cursor=length(operations) and empty(paired_replay_ev) {
            save ["waits"::waits,"statuses"::statuses,"finished_min"::at,
                "input_identity"::specification["input_identity"]] to:replay_output format:"json";
            replay_done <- true;
            write "RANR_PAIRED_PHYSICAL_REPLAY_PASS jobs="+length(waits)+" finished_min="+at;
        }
    }
}
species paired_replay_ev parent:elecar { string replay_key; }
experiment "paired_physical_replay" type:gui {
    parameter "Physical replay input" var:replay_input;
    parameter "Physical replay output" var:replay_output;
}
