model charging_service
import "ranr/Policy.gaml"

global {
    float battery_capacity_kwh <- float(ranr_environment["battery_capacity_kwh"]);
    float consumption_kwh_km <- float(ranr_environment["consumption_kwh_km"]);
    float reference_power_kw <- 60.0;
    float reference_efficiency <- 0.9;
    list<elecar> ev_population -> agents of_generic_species elecar;
    list<map> session_events <- [];
    map<string,bool> terminal_session_ids <- [];
    bool ranr_allow_mobility(elecar ev) { return true; } // Fleet supplies the energy guard.
    float ranr_trip_requirement(elecar ev) { return ev.remaining_trip_metres()*consumption_kwh_km/1000.0+ranr_safety_soc*battery_capacity_kwh/100.0; }
    action ranr_terminal_intent_event(elecar ev,string status,float at) {}
    action ranr_intent_transition(elecar ev,string state_name,float at) {}
    action ranr_queue_arrived(elecar ev) {}
    action ranr_finalize(elecar ev,string status,float at) {}
    action ranr_activity_event(elecar ev,string event_name) {}
    action ranr_session_energy_changed(elecar ev,string reason) {}
    action ranr_commit_replan(elecar ev,float at) {}
    intersection ranr_activity_destination(int node_id) { return list(intersection) first_with (each.index=node_id); }
    intersection ranr_vehicle_origin(vehicle v) { return intersection closest_to v; }
    map<string,unknown> session_snapshot(elecar ev) {
        return ["ev"::ev,"ev_id"::ev.name,"state"::ev.session_state,"rate"::ev.charge_rate,"port_rate"::ev.charge_port_rate];
    }
    action record_removed(string rid,string station_name,map data) {
        assert false;
    }
    action record_event(elecar ev,string event_type) {
        if ev.request_id="" { return nil; }
        string recorded_intent <- ev.charging_intent_id;
        bool terminal <- event_type in ["completed","service_completed","no_feasible_station","voluntary_deferred","declined","abandoned","deadline_missed","stranded","unresolved"];
        float event_at <- event_type="service_completed" ? ev.service_finish : time/60.0;
        if event_type="choice" { do ranr_intent_transition(ev,"travel",event_at); }
        if event_type="arrival" { do ranr_intent_transition(ev,"waiting",event_at); do ranr_queue_arrived(ev); }
        if event_type="service_started" { do ranr_intent_transition(ev,"charging",event_at); }
        if terminal {
            if (terminal_session_ids contains_key ev.request_id) { return nil; }
            terminal_session_ids[ev.request_id] <- true;
            do ranr_terminal_intent_event(ev,event_type="service_completed" ? "completed" : event_type,event_type="service_completed" ? ev.service_finish : time/60.0);
            ranr_terminal_events << ["request_id"::ev.request_id,"key"::ev.ranr_demand_key,"at"::(event_type="service_completed" ? ev.service_finish : time/60.0),
            "status"::(event_type="service_completed" ? "completed" : event_type),"energy"::ev.delivered_energy,"waiting"::ev.waiting_time,"travel"::ev.ranr_travel_min,"charging"::ev.ranr_charge_elapsed];
        }
        session_events << ["request_id"::ev.request_id,"token"::ev.ranr_token,"leg"::ev.ranr_leg,"event"::event_type,"time_min"::(event_type="service_completed" ? ev.service_finish : time/60.0),"energy_kwh"::ev.delivered_energy,"waiting_min"::ev.waiting_time,"travel_m"::ev.total_distance,
            "station_sid"::(ev.current_station=nil ? -1 : ev.current_station.ranr_sid),"port_id"::ev.ranr_port_id,"vehicle_id"::ev.mobility_id,"soc"::ev.battery_level,"target_soc"::ev.soc_session_target,"intent_id"::recorded_intent,"port_kw"::float(ev.charge_port_rate),"ev_limit_kw"::ev.ranr_max_kw];
    }
}

species charging_station parent:ranr_station_agent {
    list<float> ranr_release_observed_fractions <- [];
    list<float> ranr_energy_observed_fractions <- [];
    intersection closest_intersection;
    list<elecar> charging_vehicles <- [];
    list<elecar> waiting_queue <- [];
    int served_customer <- 0;
    int vehicle_waited <- 0;
    int vehicle_charged <- 0;
    int arrived_customer <- 0;
    float total_waiting_time <- 0.0; // minutes, measured at service start
    float total_charging_time <- 0.0;
    float total_distance_travel <- 0.0;
    float ranr_station_busy_minutes <- 0.0;
    float power_consumed <- 0.0; // grid energy kWh
    list<float> travel_periods <- [];
    int port_250 <- 0;
    int port_180 <- 0;
    int port_150 <- 0;
    int port_60 <- 0;
    int port_30 <- 0;
    int port_11 <- 0;
    string Address;
    bool ranr_operational <- true;
    float ranr_capacity_factor <- 1.0;
    float ranr_station_limit_kw <- -1.0;
    float ranr_pressure <- 0.0;
    float ranr_peak_pressure <- 0.0;
    int ranr_zero_capacity <- 0;
    float ranr_service_clock <- 0.0;
    list<string> ranr_connectors <- ["generic-public"];
    map<int,float> ranr_port_catalog <- [];
    list<int> ranr_failed_ports <- [];
    list<float> ranr_arrival_times <- [];
    list<float> ranr_anonymous_arrivals <- [];

    int installed_port_count -> port_250+port_180+port_150+port_60+port_30+port_11+
        length(charging_vehicles);
    float available_power_kw -> float(250*port_250+180*port_180+150*port_150+60*port_60+30*port_30+11*port_11);
    map<string,map> physical_sessions <- [];
    list<map> observed_arrivals <- [];
    int peak_physical_queue <- 0;
    aspect base { draw circle(40) color: #purple; }
    action ranr_index_ports {
        if !empty(ranr_port_catalog) { return nil; }
        int id <- 0;
        map<int,int> counts <- [250::port_250,180::port_180,150::port_150,60::port_60,30::port_30,11::port_11];
        loop rate over:CHARGING_RATES {
            if counts[rate]>0 { loop k from:1 to:counts[rate] { ranr_port_catalog[id] <- float(rate); id <- id+1; } }
        }
    }
    int ranr_free_port_id(int rate) {
        list<int> occupied <- charging_vehicles collect each.ranr_port_id;
        loop id over:ranr_port_catalog.keys { if int(ranr_port_catalog[id])=rate and !(id in occupied) and !(id in ranr_failed_ports) { return id; } }
        return -1;
    }
    int find_available_port {
        if !ranr_operational or ranr_capacity_factor<=0.0 { return 0; }
        // Lazy initialization also supports isolated physical fixtures.
        if empty(ranr_port_catalog) { do ranr_index_ports; }
        loop rate over:CHARGING_RATES { if ranr_free_port_id(rate)>=0 { return rate; } }
        return 0;
    }
    action occupy_port(int rate) {
        switch rate {
            match 250 { port_250 <- port_250 - 1; }
            match 180 { port_180 <- port_180 - 1; }
            match 150 { port_150 <- port_150 - 1; }
            match 60 { port_60 <- port_60 - 1; }
            match 30 { port_30 <- port_30 - 1; }
            match 11 { port_11 <- port_11 - 1; }
        }
    }
    action release_port(int rate) {
        switch rate {
            match 250 { port_250 <- port_250 + 1; }
            match 180 { port_180 <- port_180 + 1; }
            match 150 { port_150 <- port_150 + 1; }
            match 60 { port_60 <- port_60 + 1; }
            match 30 { port_30 <- port_30 + 1; }
            match 11 { port_11 <- port_11 + 1; }
        }
    }
    action reconcile_sessions {
        assert empty(charging_vehicles where (dead(each)));
        assert empty(waiting_queue where (dead(each)));
    }
    action enqueue_arrival(elecar ev) {
        if ev = nil or dead(ev) or ev.current_station != self or !(ev.session_state in ["requested","assigned","en_route"]) { return nil; }
        if ev.arrival_time >= 0.0 { return nil; }
        if closest_intersection != nil and ev.location distance_to closest_intersection.location >= 2.0 { return nil; }
        if ev.station_arrival_due > time / 60.0 + 1e-10 { return nil; }
        if ev.charging_intent_id!="" {
            ev.requested_energy <- ev.delivered_energy+max(0.0,ev.soc_session_target-ev.battery_level)*battery_capacity_kwh/100.0;
            ask world { do ranr_session_energy_changed(ev,"arrival_soc"); }
        }
        // Reconcile forecast energy with actual arrival SOC only after removing inbound.
        // Frozen optimization coefficients remain in the exported batch snapshot.
        if ranr_calibrating and time/60.0>=ranr_warmup and ranr_energy_width>0.0 {
            float fraction <- ev.requested_energy/ranr_energy_width-floor(ev.requested_energy/ranr_energy_width);
            ranr_energy_observed_fractions << fraction;
        }
        ev.arrival_time <- time / 60.0;
        ranr_arrival_times << ev.arrival_time;
        // The EV deliberately presents its protocol token on physical arrival.
        if ev.ranr_token!="" {
            do ranr_resolve(ev.ranr_token,"arrived",ev.arrival_time);
            map<string,unknown> resolution <- world.ranr_record(ranr_resolutions[ev.ranr_token]); resolution["energy"] <- max(0.0,ev.requested_energy-ev.delivered_energy); resolution["max_kw"] <- ev.ranr_max_kw; resolution["deadline"] <- ev.ranr_deadline_at; ranr_resolutions[ev.ranr_token] <- resolution;
        }
        else { ranr_anonymous_arrivals << ev.arrival_time; }
        observed_arrivals << ["at"::ev.arrival_time,"energy"::ev.requested_energy];
        ev.session_state <- "waiting";
        arrived_customer <- arrived_customer + 1;
        travel_periods << ev.total_distance;
        total_distance_travel <- sum(travel_periods);
        waiting_queue << ev;
        physical_sessions[ev.request_id] <- world.session_snapshot(ev);
        ask world { do record_event(ev, "arrival"); }
        do process_queue;
        peak_physical_queue <- max(peak_physical_queue,length(waiting_queue));
        if ev.session_state = "waiting" { vehicle_waited <- vehicle_waited + 1; }
    }
    action process_queue {
        if waiting_queue=nil { write "NIL_QUEUE "+self+" "+species(self); assert false; }
        do reconcile_sessions;
        waiting_queue <- waiting_queue where (!dead(each) and each.session_state = "waiting");
        loop while: !empty(waiting_queue) and find_available_port() > 0 {
            elecar ev <- waiting_queue[0];
            if !(ev.ranr_connector in ranr_connectors) { break; }
            remove ev from: waiting_queue;
            int rate <- find_available_port();
            ev.ranr_port_id <- ranr_free_port_id(rate);
            assert ev.ranr_port_id>=0;
            do occupy_port(rate);
            charging_vehicles << ev;
            vehicle_charged <- vehicle_charged + 1;
            ev.charge_port_rate <- rate;
            ev.charge_rate <- min(rate*ranr_capacity_factor,ev.ranr_max_kw);
            ev.is_charging <- true;
            ev.session_state <- "charging";
            ev.service_start <- time / 60.0;
            ev.ranr_last_integrated <- ev.service_start;
            ev.waiting_time <- ev.ranr_previous_wait+ev.service_start-ev.arrival_time;
            total_waiting_time <- total_waiting_time + ev.waiting_time;
            physical_sessions[ev.request_id] <- world.session_snapshot(ev);
            ask world { do record_event(ev, "service_started"); }
        }
    }
    action cancel_session(elecar ev) {
        remove ev from: waiting_queue;
        if ev in charging_vehicles {
            remove ev from: charging_vehicles;
            do release_port(ev.charge_port_rate);
        }
        remove key: ev.request_id from: physical_sessions;
    }
    float get_average_waiting_time { return vehicle_charged > 0 ? total_waiting_time / vehicle_charged : 0.0; }
    float get_average_charging_time { return served_customer > 0 ? total_charging_time / served_customer : 0.0; }
    float get_total_distance { return arrived_customer > 0 ? total_distance_travel / arrived_customer : 0.0; }
    bool check_in_queue(vehicle ev) { return ev in waiting_queue; }
    action ranr_capture(float at) {
        do ranr_index_ports;
        list<float> powers <- []; list<float> lower <- []; list<float> upper <- [];
        list<int> occupied <- charging_vehicles collect each.ranr_port_id;
        loop id over:ranr_port_catalog.keys {
            if id in occupied { continue; }
            powers << (ranr_operational and !(id in ranr_failed_ports) ? ranr_port_catalog[id]*ranr_capacity_factor : 0.0); lower << 0.0; upper << 0.0;
        }
        loop ev over: charging_vehicles {
            powers << (ranr_operational and !(ev.ranr_port_id in ranr_failed_ports) ? float(ev.charge_port_rate)*ranr_capacity_factor : 0.0);
            float remaining <- max(0.0,ev.requested_energy-ev.delivered_energy);
            float live_power <- ranr_operational and !(ev.ranr_port_id in ranr_failed_ports) ? min(float(ev.charge_port_rate)*ranr_capacity_factor,ev.ranr_max_kw) : 0.0;
            float release <- live_power>0.0 ? (step/60.0)*ceil((60.0*remaining/(charge_efficiency*live_power))/(step/60.0)-1e-10) : 1e100;
            float lo <- ranr_snapshot_width>0.0 ? ranr_snapshot_width*floor(release/ranr_snapshot_width) : release;
            if ranr_calibrating and at>=ranr_warmup and ranr_snapshot_width>0.0 { ranr_release_observed_fractions << (release-lo)/ranr_snapshot_width; }
            lower << release; upper << release;
        }
        list<map> queue <- [];
        loop ev over: waiting_queue {
            float energy <- max(0.0,ev.requested_energy-ev.delivered_energy);
            float lo <- ranr_energy_width>0.0 ? ranr_energy_width*floor(energy/ranr_energy_width) : energy;
            if ranr_calibrating and at>=ranr_warmup and ranr_energy_width>0.0 { ranr_energy_observed_fractions << (energy-lo)/ranr_energy_width; }
            queue << ["low"::energy,"high"::energy,"max_kw"::ev.ranr_max_kw,"token"::ev.ranr_token,"service_until"::1e100];
        }
        ranr_local_snapshot <- ["sid"::ranr_sid,"issued"::at,"powers"::powers,"release_lo"::lower,"release_hi"::upper,"queue"::queue,"aggregate_kw"::ranr_aggregate_limit(),"source"::"local","operational"::ranr_operational,"connectors"::copy(ranr_connectors),"anonymous_count"::length(ranr_anonymous_arrivals where (each>max(0.0,at-5.0) and each<=at)),"anonymous_window"::max(0.0,at-5.0)];
    }
    list<float> ranr_physical_powers {
        list<float> powers <- [];
        loop port_id over:ranr_port_catalog.keys { powers << (ranr_operational and !(port_id in ranr_failed_ports) ? float(ranr_port_catalog[port_id])*ranr_capacity_factor : 0.0); }
        return powers;
    }
    float ranr_aggregate_limit {
        float nominal <- sum(list<float>(ranr_port_catalog.values));
        map<string,unknown> configured <- ranr_environment["station_aggregate_power_kw"];
        float limit <- ranr_station_limit_kw>=0.0 ? ranr_station_limit_kw : (configured contains_key name ? float(configured[name]) : nominal);
        return ranr_operational ? max(0.0,limit*ranr_capacity_factor) : 0.0;
    }
    list<map<string,unknown>> ranr_active_jobs {
        list<map<string,unknown>> jobs <- [];
        loop ev over:charging_vehicles {
            jobs << ["port"::ev.ranr_port_id,"at"::0.0,"energy"::max(0.0,ev.requested_energy-ev.delivered_energy),"max_kw"::ev.ranr_max_kw,"soc"::ev.battery_level];
        }
        return jobs;
    }
    action ranr_measure_pressure {
        float energy <- sum(waiting_queue collect max(0.0,each.requested_energy-each.delivered_energy));
        ranr_pressure <- 0.0;
        if energy>1e-9 {
            list<map<string,unknown>> jobs <- ranr_active_jobs();
            loop ev over:waiting_queue { jobs << ["at"::0.0,"energy"::max(0.0,ev.requested_energy-ev.delivered_energy),"max_kw"::ev.ranr_max_kw,"soc"::ev.battery_level]; }
            float backlog <- sum(jobs collect float(each["energy"]));
            map<string,unknown> forecast <- world.ranr_service_schedule(ranr_physical_powers(),jobs,ranr_aggregate_limit(),1e6);
            float effective <- bool(forecast["cleared"]) and float(forecast["duration"])>1e-9 ? backlog*60.0/float(forecast["duration"]) : 0.0;
            ranr_pressure <- effective>0.0 ? energy/(energy+effective*6.0) : 1.0;
            if effective<=0.0 { ranr_zero_capacity <- ranr_zero_capacity+1; }
        }
        ranr_peak_pressure <- max(ranr_peak_pressure,ranr_pressure);
    }
    action ranr_advance_service(float at) {
        do reconcile_sessions;
        float elapsed <- max(0.0,at-ranr_service_clock);
        list<elecar> owners <- copy(charging_vehicles);
        if !empty(owners) and elapsed>1e-10 {
            map<string,unknown> integrated <- world.ranr_service_schedule(ranr_physical_powers(),ranr_active_jobs(),ranr_aggregate_limit(),elapsed);
            list<float> energies <- integrated["delivered"]; list<float> finishes <- integrated["finishes"];
            loop j from:0 to:length(owners)-1 {
                elecar ev <- owners[j]; float energy <- energies[j];
                float active_duration <- finishes[j]>=0.0 ? finishes[j] : elapsed;
                ev.delivered_energy <- ev.delivered_energy+energy;
                ev.ranr_lifetime_charged_kwh <- ev.ranr_lifetime_charged_kwh+energy;
                ev.battery_level <- ev.battery_level+100.0*energy/battery_capacity_kwh;
                ev.ranr_charge_elapsed <- ev.ranr_charge_elapsed+active_duration;
                ev.charging_time <- ev.charging_time+(energy>1e-12 ? active_duration : 0.0);
                ev.charge_rate <- active_duration>0.0 ? energy*60.0/(charge_efficiency*active_duration) : 0.0;
                power_consumed <- power_consumed+energy/charge_efficiency;
                float busy <- max(0.0,min(ranr_service_clock+active_duration,ranr_warmup+ranr_measure)-max(ranr_service_clock,ranr_warmup));
                ranr_busy_port_minutes <- ranr_busy_port_minutes+busy; ranr_station_busy_minutes <- ranr_station_busy_minutes+busy;
                ev.ranr_last_integrated <- at;
                if finishes[j]>=0.0 {
                    ev.service_finish <- ranr_service_clock+finishes[j]; ev.completion_pending <- true;
                    ask ev { do stop_charging; }
                }
            }
        }
        ranr_service_clock <- at;
        ask waiting_queue { waiting_time <- ranr_previous_wait+max(0.0,at-arrival_time); }
    }

}

// Electric vehicles and their charging-session lifecycle.
species elecar parent: vehicle {
    bool is_ev <- true;
    float vehicle_length <- 4.5 #m;
    int num_lanes_occupied <- 1;
    float max_speed <- ele_car_speed #km / #h;
    charging_station current_station;
    list<charging_station> all_stations <- [];
    float battery_level <- rnd(40.0,100.0);
    float charge_rate <- 0.0;
    int charge_port_rate <- 0;
    int ranr_port_id <- -1;
    float ranr_max_kw <- 120.0;
    float ranr_last_integrated <- 0.0;
    string ranr_connector <- "generic-public";
    string ranr_token <- "";
    int ranr_issuer <- -1;
    int ranr_leg <- 0;
    list<int> ranr_unavailable_sids <- [];
    float ranr_charge_elapsed <- 0.0;
    float ranr_previous_wait <- 0.0;
    int ranr_demand_key <- -1;
    bool ranr_participating <- true;
    bool ranr_measured <- false;
    float soc_request_threshold <- 30.0;
    float soc_preferred_target <- 80.0;
    float soc_session_target <- 80.0;
    string charging_intent_id <- "";
    int charging_intent_sequence <- 0;
    int charging_attempt_count <- 0;
    string charging_need_reason <- "";
    string charging_deferred_reason <- "";
    string charging_retry_trigger <- "new_intent";
    float ranr_deadline_at <- -1.0;
    float charging_last_checked_soc <- -1.0;
    float charging_last_attempt_soc <- 100.0;
    path charging_last_checked_path;
    bool charging_activity_event <- true;
    bool ranr_replan_pending <- false;
    bool ranr_at_replan_node <- false;
    bool ranr_road_clear_pending <- false;
    int charging_last_shift_cursor <- -1;
    float charging_shift_energy <- 0.0;
    list<map<string,unknown>> activity_schedule <- [];
    int activity_cursor <- 0;
    bool activity_prepared <- false;
    bool activity_in_progress <- false;
    string current_activity <- "parked";
    float activity_hold_until <- -1.0;
    bool taxi_has_passenger -> ranr_vehicle_kind="taxi" and activity_in_progress and current_activity="passenger";
    float external_factor_impact(agent new_road,float remaining_time) {
        if ranr_replan_pending or ranr_road_clear_pending { ranr_at_replan_node <- true; return 0.0; }
        return remaining_time;
    }
    float ranr_next_energy_attempt <- 0.0;
    path ranr_energy_checked_path;
    float ranr_destination_station_metres <- 0.0;
    float ranr_travel_min <- 0.0;
    map<string,unknown> ranr_result <- [];
    float waiting_time <- 0.0;
    float charging_time <- 0.0;
    float total_distance <- 0.0;
    string request_id <- "";
    string session_state <- "idle";
    float requested_energy <- 0.0;
    float delivered_energy <- 0.0;
    float request_time <- -1.0;
    float commit_time <- -1.0;
    float assigned_eta <- -1.0;
    float assigned_travel_energy <- 0.0;
    float arrival_time <- -1.0;
    float station_arrival_due <- -1.0;
    float service_start <- -1.0;
    float service_finish <- -1.0;
    bool completion_pending <- false;
    float workload <- 0.0;
    charging_station recommended_station;
    charging_station actual_chosen_station;
    bool recommendation_followed <- false;
    action apply_station_choice(charging_station destination_station, float predicted_eta, float predicted_energy, float energy_to_receive, float predicted_workload) {
        if !(session_state in ["requested","deferred"]) or destination_station = nil { return nil; }
        current_station <- destination_station;
        actual_chosen_station <- destination_station;
        commit_time <- time/60.0;
        total_distance <- 0.0;
        assigned_eta <- predicted_eta;
        assigned_travel_energy <- predicted_energy;
        if charging_intent_id!="" {
            requested_energy <- max(0.0,(soc_session_target-battery_level)*battery_capacity_kwh/100.0+predicted_energy);
            workload <- 60.0*requested_energy/(reference_efficiency*reference_power_kw);
            ask world { do ranr_session_energy_changed(myself,"selected_route"); }
        }
        recommendation_followed <- destination_station = recommended_station;
        session_state <- "en_route";
        station_arrival_due <- -1.0;
        ask world { do record_event(myself,"choice"); do record_event(myself,"en_route"); }
        do compute_path graph: road_network source:world.ranr_vehicle_origin(self) target: destination_station.closest_intersection;
        if final_target = nil and location distance_to destination_station.closest_intersection.location < 2.0 { do start_charging; }
    }

    action begin_request {
        if needs_charging { return nil; }

        assert reference_efficiency > 0.0 and reference_efficiency <= 1.0 and reference_power_kw > 0.0;
        request_id <- "ranr_"+ranr_demand_key;
        ranr_issuer <- -1; ranr_leg <- 0; ranr_unavailable_sids <- []; ranr_token <- ""; ranr_charge_elapsed <- 0.0; ranr_previous_wait <- 0.0; ranr_travel_min <- 0.0;
        session_state <- "requested";
        needs_charging <- true;
        request_time <- time / 60.0;
        if charging_intent_id="" { ranr_deadline_at <- request_time+ranr_deadline; }
        commit_time <- -1.0;
        assigned_eta <- -1.0;
        assigned_travel_energy <- 0.0;
        arrival_time <- -1.0;
        station_arrival_due <- -1.0;
        service_start <- -1.0;
        service_finish <- -1.0;
        completion_pending <- false;
        delivered_energy <- 0.0;
        workload <- 60.0 * requested_energy / (reference_efficiency * reference_power_kw);
        waiting_time <- 0.0;
        charging_time <- 0.0;
        total_distance <- 0.0;
        recommended_station <- nil; actual_chosen_station <- nil;
        recommendation_followed <- false;
        temp_target <- target;
        ask world { do record_event(myself, "request"); }
    }
    action start_charging {
        // Compatibility entry point: arrival is idempotent, not a repeated port poll.
        if current_station = nil { return nil; }
        if session_state in ["completed","cancelled","stranded"] { return nil; }
        if request_id="" { return nil; }
        ask current_station { do enqueue_arrival(myself); }
    }
    action stop_charging {
        if session_state != "charging" or !completion_pending or time/60.0 + 1e-10 < service_finish { return nil; }
        session_state <- "completed";
        ask world { do record_event(myself, "service_completed"); }
        ask current_station {
            remove myself from: charging_vehicles;
            remove key: myself.request_id from: physical_sessions;
            do release_port(myself.charge_port_rate);
            served_customer <- served_customer + 1;
            total_charging_time <- total_charging_time + myself.charging_time;
            // Dispatch next EV on next tick, preventing service before interval end.
        }
        completion_pending <- false;
        is_charging <- false;
        needs_charging <- false;
        charge_rate <- 0.0;
        current_station <- nil;
    }
    action cancel_request(string reason) {
        if reason="deadline_missed" { return nil; } // Evaluation deadlines cannot terminate physical service.
        if !needs_charging { return nil; }
        if session_state in ["cancelled","stranded","completed","no_feasible_station","voluntary_deferred","declined","abandoned","deadline_missed"] { return nil; }
        if current_station != nil { ask current_station { do cancel_session(myself); } }
        bool clear_road <- false;
        if current_road!=nil and final_target!=nil and current_path!=nil {
            clear_road <- location distance_to world.ranr_vehicle_origin(self).location>1e-6;
        }
        session_state <- reason;
        ask world { do record_event(myself, reason); }
        if clear_road {
            ranr_road_clear_pending <- true; ranr_replan_pending <- false; ranr_at_replan_node <- false;
        } else { do unregister; final_target <- nil; }
        needs_charging <- false;
        is_charging <- false;
        current_station <- nil;
        charge_rate <- 0.0;
    }
    reflex cease when: battery_level <= 0 and !is_charging and !ranr_stranded {
        do cancel_request("stranded");
        lost_car_location << location;
        batter_insufficient <- batter_insufficient + 1;
        do unregister; final_target <- nil; ranr_stranded <- true;
    }
    reflex move when: final_target != nil and battery_level > 0 and !is_charging {
        if !world.ranr_allow_mobility(self) { speed <- 0.0; return nil; }
        float movement_started <- machine_time;
        float previous_remaining <- remaining_trip_metres();
        max_speed <- (ele_car_speed #km / #h) * world.road_speed_factor(road(current_road));
        // A nearly empty battery cannot fund more distance than one native step.
        max_speed <- min(max_speed,battery_level*battery_capacity_kwh*10.0/(max(1e-12,consumption_kwh_km)*step));
        speed <- min(speed,max_speed);
        do drive;
        float travelled <- max(0.0,previous_remaining - remaining_trip_metres());
        ranr_lifetime_metres <- ranr_lifetime_metres+travelled;
        battery_level <- max(0.0,battery_level - 100.0 * consumption_kwh_km * travelled / (1000.0 * battery_capacity_kwh));
        if needs_charging { total_distance <- total_distance + travelled; if ranr_enabled { ranr_travel_min <- ranr_travel_min+step/60.0; } }
        if ranr_enabled { ranr_movement_ms <- ranr_movement_ms+machine_time-movement_started; }
        if ranr_replan_pending and ranr_at_replan_node {
            ask world { do ranr_commit_replan(myself,(time+step)/60.0); }
        }
        if ranr_road_clear_pending and ranr_at_replan_node {
            do unregister; final_target <- nil;
            ranr_road_clear_pending <- false; ranr_at_replan_node <- false; activity_prepared <- false;
        }
        if needs_charging and current_station != nil and final_target = nil and travelled > 0.0 {
            station_arrival_due <- (time + step) / 60.0;
        }
        if final_target = nil { do unregister; }
        shift_pt <- compute_position();
    }

    // Personal schedules are mobility plans, never clocks granting permission to charge.
    reflex work_vehicle_behavior {}
    reflex entertainment_behavior {}
    reflex update_schedule {}
    reflex personal_activity when:!ranr_stranded and !empty(activity_schedule) {
        do advance_personal_activity;
    }
    action advance_personal_activity {
        // A cancelled charging trip can still own a road segment. Native
        // compute_path projects location onto its source vertex; wait for the
        // driving callback to reach that vertex and clear the pending route.
        if ranr_road_clear_pending or ranr_replan_pending { return nil; }
        float at <- time/60.0;
        if activity_in_progress {
            if final_target=nil {
                intersection activity_node <- world.ranr_activity_destination(int(activity_schedule[activity_cursor]["node"]));
                if location distance_to activity_node.location<2.0 {
                    ask world { do ranr_activity_event(myself,"arrived"); }
                    activity_hold_until <- at+float(activity_schedule[activity_cursor]["duration"]);
                    activity_cursor <- activity_cursor+1;
                } else { ask world { do ranr_activity_event(myself,"route_unavailable"); } activity_cursor <- activity_cursor+1; }
                activity_in_progress <- false; activity_prepared <- false;
                current_activity <- current_activity="break" ? "break" : (ranr_vehicle_kind="taxi" ? "between_passengers" : "parked");
            }
            return nil;
        }
        if needs_charging or is_charging or at<activity_hold_until or activity_cursor>=length(activity_schedule) { return nil; }
        map<string,unknown> activity <- activity_schedule[activity_cursor];
        if at<float(activity["at"]) { return nil; }
        if activity["kind"]="passenger" and at>=float(activity["shift_end"]) {
            current_activity <- "off_shift";
            ask world { do ranr_activity_event(myself,"missed_service"); }
            activity_cursor <- activity_cursor+1; activity_prepared <- false; return nil;
        }
        if !activity_prepared {
            current_activity <- string(activity["kind"]);
            intersection activity_node <- world.ranr_activity_destination(int(activity["node"]));
            do compute_path graph:road_network source:world.ranr_vehicle_origin(self) target:activity_node;
            activity_prepared <- true; charging_activity_event <- true;
            ask world { do ranr_activity_event(myself,"prepared"); }
            if world.ranr_trip_requirement(self)>battery_capacity_kwh {
                ask world { do ranr_activity_event(myself,"trip_exceeds_battery_capacity"); }
                do unregister; final_target <- nil;
                activity_cursor <- activity_cursor+1; activity_prepared <- false;
                if charging_intent_id="" { charging_need_reason <- ""; }
                return nil;
            }
        }
        if !world.ranr_allow_mobility(self) { return nil; }
        activity_in_progress <- true;
        if activity["kind"]="exit" { ranr_exiting <- true; }
        ask world { do ranr_activity_event(myself,"departed"); }
    }

}

species private_ev parent: elecar {
    init { if ranr_enabled { mobility_id <- 10000+index; } }
    image_file my_icon <- image_file("../includes/vinfast.png");

}

species taxi_ev parent: elecar {
    init { if ranr_enabled { mobility_id <- 20000+index; } }
    image_file my_icon <- image_file("../includes/xanhsm.png");
}
