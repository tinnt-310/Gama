model ranr_energy_tests
import "../main.gaml"

global {
    string fixture_mode <- "low";
    float step <- 60.0;
    int cars <- 2; int privates <- 2; int taxis <- 2;
    bool ranr_development <- true; bool ranr_gui_preview <- false;
    bool ranr_render <- false; bool have_rush <- false;
    bool ranr_calibrating <- true;
    float ranr_true_defer <- 0.0; float ranr_true_compliance <- 1.0;
    float ranr_warmup <- 0.0; float ranr_measure <- 240.0; float ranr_deadline <- 360.0;
    int ranr_samples <- 1;
    string ranr_run_id <- "energy_fixture";
    string ranr_output <- "../../outputs/gama_ranr/energy_fixture";
    elecar probe;
    string original_intent <- "";
    float initial_probe_soc <- 0.0;
    bool fixture_checked <- false;
    point fixture_last_location;
    float fixture_last_metres <- 0.0;
    bool fixture_outage_sent <- false;

    action ranr_fleet_initialized {
        if fixture_mode="drive" { return nil; }
        ask ev_population { battery_level <- 100.0; soc_request_threshold <- 15.0; soc_preferred_target <- 90.0; soc_session_target <- 90.0; activity_schedule <- []; }
        probe <- fixture_mode in ["passenger","shift"] ? taxi_ev[0] : private_ev[0];
        charging_station origin_station <- ranr_stations[0];
        ask probe { do unregister; final_target <- nil; location <- origin_station.closest_intersection.location; battery_level <- 29.0; soc_request_threshold <- 30.0; ranr_max_kw <- 120.0; }
        if fixture_mode="target" { probe.soc_preferred_target <- 100.0; probe.soc_session_target <- 100.0; }
        if fixture_mode="shift" {
            probe.battery_level <- 20.0; probe.soc_request_threshold <- 15.0; probe.current_activity <- "off_shift";
            probe.activity_schedule <- [["vehicle_id"::probe.mobility_id,"sequence"::0,"at"::10.0,"kind"::"passenger","node"::origin_station.closest_intersection.index,"duration"::0.0,"shift_end"::240.0],
                ["vehicle_id"::probe.mobility_id,"sequence"::1,"at"::180.0,"kind"::"break","node"::origin_station.closest_intersection.index,"duration"::30.0,"shift_end"::240.0]];
        }
        if fixture_mode in ["replan","cancel"] {
            // A reproducible GIS node exercises a mid-road outage, rather than
            // relying on unordered connected-component iteration to select a node.
            intersection fixture_node <- access_intersections closest_to {15865.623013002565,30734.402660797583};
            assert fixture_node.location distance_to {15865.623013002565,30734.402660797583}<1e-3;
            probe.location <- fixture_node.location;
        }
        if fixture_mode in ["long_insufficient","long_feasible","activity","passenger"] {
            bool long_trip <- fixture_mode in ["long_insufficient","long_feasible"];
            bool found <- false;
            loop destination over:(access_intersections where (each.location distance_to probe.location>(long_trip ? 12000.0 : 1000.0) and each.location distance_to probe.location<(long_trip ? 22000.0 : 4000.0))) {
                path route <- path_between(road_network,origin_station.closest_intersection,destination);
                float metres <- route=nil ? -1.0 : sum(route.edges collect each.perimeter);
                if metres>(long_trip ? 20000.0 : 1000.0) and metres<(long_trip ? 30000.0 : 5000.0) {
                    probe.activity_schedule <- [["vehicle_id"::probe.mobility_id,"sequence"::0,"at"::0.0,"kind"::(fixture_mode="passenger" ? "passenger" : "personal"),"node"::destination.index,"duration"::0.0,"shift_end"::600.0]];
                    probe.current_activity <- fixture_mode="passenger" ? "passenger" : "personal";
                    intersection target_node <- intersection(destination);
                    ask probe { do compute_path graph:road_network source:origin_station.closest_intersection target:target_node; }
                    probe.activity_prepared <- true;
                    probe.activity_in_progress <- !long_trip;
                    probe.battery_level <- fixture_mode="long_feasible" ? 95.0 : (long_trip ? 35.0 : 45.0);
                    probe.soc_request_threshold <- long_trip ? 15.0 : 60.0;
                    found <- true; break;
                }
            }
            assert found;
            if fixture_mode="long_insufficient" {
                write "TRIP_ENERGY_DIAGNOSTIC soc="+probe.battery_level+" consumption="+consumption_kwh_km+" remaining="+probe.remaining_trip_metres()+" required="+ranr_planned_energy(probe)+" target="+probe.final_target+" active="+probe.activity_in_progress+" ready="+ranr_fleet_ready;
                assert !ranr_allow_mobility(probe);
            }
            if fixture_mode="long_feasible" { assert ranr_allow_mobility(probe); }
        }
        if fixture_mode in ["unavailable","drain"] {
            ask ranr_stations { ranr_operational <- false; }
            loop prior over:ranr_public_priors { prior["operational"] <- false; }
        }
        if fixture_mode="deadline" {
            ask ranr_stations { ranr_operational <- false; }
            ask ranr_stations[0] { ranr_operational <- true; ranr_capacity_factor <- 0.05; }
            loop sid from:0 to:length(ranr_public_priors)-1 { ranr_public_priors[sid]["operational"] <- sid=0; }
        }
        initial_probe_soc <- probe.battery_level;
        fixture_last_location <- probe.location;
    }
    reflex fixture_first_attempt when:cycle=1 and fixture_mode!="drive" {
        if fixture_mode="long_feasible" { assert empty(ranr_attempts); }
        else {
            assert length(ranr_intents)=1;
            original_intent <- probe.charging_intent_id;
            if fixture_mode in ["activity","passenger"] {
                assert probe.activity_in_progress and !probe.needs_charging and empty(ranr_attempts);
                if fixture_mode="passenger" { assert probe.taxi_has_passenger; }
            } else {
                assert length(ranr_attempts)=1;
                if fixture_mode="long_insufficient" { assert ranr_intents[original_intent]["cause"]="trip_energy" and !probe.activity_in_progress; }
                if fixture_mode="shift" { assert ranr_intents[original_intent]["cause"]="shift_energy" and probe.battery_level>probe.soc_request_threshold; }
                if fixture_mode in ["low","target"] {
                    int before <- length(ranr_attempts);
                    do ranr_start_attempt(probe);
                    assert length(ranr_attempts)=before;
                }
            }
        }
    }
    reflex fixture_restore when:cycle=10 and fixture_mode in ["unavailable","drain"] {
        ask ranr_stations[0] { ranr_operational <- true; ranr_critical <- true; }
        probe.charging_activity_event <- true;
    }
    reflex fixture_no_new_drain_intent when:cycle=2 and fixture_mode="drain" {
        private_ev[1].battery_level <- 20.0;
        private_ev[1].charging_activity_event <- true;
    }
    reflex fixture_outage when:cycle=2 and fixture_mode="replan" {
        assert probe.session_state="en_route";
        charging_station failed <- probe.current_station;
        ask failed { ranr_operational <- false; ranr_critical <- true; do ranr_capture(time/60.0); }
        do ranr_broadcast(failed,time/60.0);
        fixture_outage_sent <- true;
    }
    reflex fixture_cancel_midroad when:cycle=2 and fixture_mode="cancel" {
        assert probe.session_state="en_route" and probe.current_road!=nil and probe.final_target!=nil;
        probe.activity_schedule <- [["vehicle_id"::probe.mobility_id,"sequence"::0,"at"::0.0,"kind"::"personal","node"::ranr_stations[1].closest_intersection.index,"duration"::0.0,"shift_end"::600.0]];
        probe.activity_cursor <- 0; probe.activity_prepared <- false; probe.activity_in_progress <- false;
        ask probe { do cancel_request("abandoned"); }
        assert probe.ranr_road_clear_pending;
        path cancelled_route <- probe.current_path;
        point cancellation_position <- probe.location;
        ask probe { do advance_personal_activity; }
        assert !probe.activity_prepared and !probe.activity_in_progress;
        assert probe.current_path=cancelled_route and probe.location=cancellation_position;
    }
    reflex fixture_no_teleport when:fixture_mode!="drive" {
        assert probe.location distance_to fixture_last_location<=probe.ranr_lifetime_metres-fixture_last_metres+1e-3;
        fixture_last_location <- probe.location; fixture_last_metres <- probe.ranr_lifetime_metres;
    }
    reflex fixture_verify when:cycle=239 and !(fixture_mode in ["drive","deadline"]) {
        if fixture_mode="replan" {
            write "REPLAN_DIAGNOSTIC station="+probe.current_station+" arrival="+probe.arrival_time+" due="+probe.station_arrival_due+" final="+probe.final_target+" distance="+(probe.current_station=nil ? -1.0 : probe.location distance_to probe.current_station.closest_intersection.location)+" pending="+probe.ranr_replan_pending+" clear="+probe.ranr_road_clear_pending;
        }
        assert !dead(probe) and !probe.ranr_stranded;
        if fixture_mode="retry" {
            assert length(ranr_intents)=1 and length(ranr_attempts)<=1+int(time/60.0/ranr_energy_retry_minutes);
            assert length(ranr_attempts)>1;
            assert length(remove_duplicates(ranr_attempts collect string(each["intent_id"])))=1;
            assert probe.charging_intent_id=original_intent;
            assert probe.battery_level=initial_probe_soc and probe.ranr_lifetime_charged_kwh=0.0;
        } else if fixture_mode="long_feasible" {
            assert probe.activity_cursor=1 and !probe.activity_in_progress;
            assert probe.ranr_lifetime_metres>20000.0 and probe.ranr_lifetime_charged_kwh=0.0;
            assert empty(ranr_attempts);
        } else {
            assert !empty(ranr_intent_outcomes);
            assert length(list(ranr_intent_outcomes.values) where (each["status"]="completed"))>=1;
            assert probe.ranr_lifetime_charged_kwh>0.0;
            if fixture_mode in ["low","target"] { assert abs(probe.battery_level-probe.soc_preferred_target)<1e-6; }
            if fixture_mode in ["activity","passenger"] {
                assert probe.activity_cursor=1;
                assert ranr_attempts[0]["intent_id"]=original_intent;
                assert !bool(ranr_attempts[0]["passenger"]);
            }
            if fixture_mode="unavailable" { assert length(ranr_attempts)>1 and length(ranr_intents)=1; }
            if fixture_mode="drain" { assert length(ranr_intents)=1 and private_ev[1].charging_intent_id="" and float(ranr_attempts[length(ranr_attempts)-1]["at"])>ranr_measure; }
            if fixture_mode="replan" { assert fixture_outage_sent and !empty(session_events where (each["event"]="replan")); }
        }
        assert abs(probe.battery_level-(initial_probe_soc+100.0*(probe.ranr_lifetime_charged_kwh-probe.ranr_lifetime_metres*consumption_kwh_km/1000.0)/battery_capacity_kwh))<1e-6;
        assert sum(ranr_stations collect each.installed_port_count)=125;
        assert empty(ranr_outcomes.values where (each["requested_kwh"]=nil or each["replans"]=nil));
        assert empty(ranr_stations where (length(remove_duplicates(each.charging_vehicles))!=length(each.charging_vehicles)));
        do ranr_flush;
        write "RANR_SOC_ACTIVITY_PASS "+fixture_mode;
    }
    reflex fixture_deadline_continues when:fixture_mode="deadline" and cycle=361 {
        assert probe.charging_intent_id=original_intent;
        assert probe.ranr_deadline_at=360.0;
        assert probe.is_charging and probe in ranr_stations[0].charging_vehicles;
        ask probe { do cancel_request("deadline_missed"); }
        assert probe.is_charging and probe in ranr_stations[0].charging_vehicles;
        assert bool(ranr_intents[original_intent]["deadline_missed"]);
        assert empty(ranr_intent_outcomes);
    }
    reflex fixture_late_completion when:fixture_mode="deadline" and cycle=1000 {
        assert length(ranr_intent_outcomes)=1;
        map<string,unknown> result <- ranr_intent_outcomes[original_intent];
        assert result["status"]="completed" and bool(result["energy_complete"]);
        assert bool(result["deadline_missed"]) and !bool(result["on_time"]);
        assert float(result["actual_completion_time"])>720.0;
        assert float(result["completion_time_min"])>720.0;
        assert abs(float(result["delivered_kwh"])-float(result["requested_kwh"]))<1e-6;
        assert length(ranr_attempts)=1;
        write "RANR_DEADLINE_DRAIN_PASS";
    }
    reflex fixture_three_days when:fixture_mode="drive" and ranr_done and !fixture_checked {
        fixture_checked <- true;
        assert !ranr_failed and length(ranr_city_vehicles)=6;
        assert empty(ranr_city_vehicles where each.ranr_stranded);
        assert !empty(ranr_intents) and length(ranr_intent_outcomes)=length(ranr_intents);
        assert length(ranr_demands)=length(ranr_outcomes);
        assert day_counter=4;
        write "RANR_SOC_ACTIVITY_THREE_DAYS_PASS";
    }
}
experiment "ranr_energy" type:gui parent:"Run me" {
    parameter "Energy fixture" var:fixture_mode among:["low","target","long_insufficient","long_feasible","activity","passenger","shift","retry","unavailable","drain","replan","cancel","drive","deadline"];
}
