model charging_service
import "ranr/Policy.gaml"

// EV and station lifecycle share one compilation unit because they reference each other.

global {
    string runtime_mode <- "IDEAL_COORDINATED_ASSIGNMENT";
    float battery_capacity_kwh <- float(ranr_environment["battery_capacity_kwh"]);
    float consumption_kwh_km <- 0.18;
    float home_power_kw <- 7.0;
    float reference_power_kw <- 60.0;
    float reference_efficiency <- 0.9; // Fixed workload unit; distinct from physical efficiency.
    string charging_goal <- "fixed_request"; // Legacy fixtures; Run me selects target_soc.
    string service_backend <- "fixed_port";
    string mock_profile <- "constant";
    float mock_capacity_per_bin <- 10.0;
    int session_sequence <- 0;
    list<map> session_events <- [];
    map<string,bool> terminal_session_ids <- [];
    // Requests have no station owner until assignment; retain only their audit metadata here.
    map<string,map> pending_session_data <- [];
    list<elecar> ev_population -> (agents of_generic_species elecar);

    map session_snapshot(elecar ev) {
        return ["ev"::ev,"ev_id"::ev.name,"requested_kwh"::ev.requested_energy,
        "energy_kwh"::ev.delivered_energy,"waiting_min"::ev.waiting_time,
        "travel_m"::ev.total_distance,"arrival_min"::ev.arrival_time,"commit_min"::ev.commit_time,"eta_min"::ev.assigned_eta,
        "state"::ev.session_state,"rate"::ev.charge_rate,"port_rate"::ev.charge_port_rate,
        "soc"::ev.battery_level,"travel_kwh"::(consumption_kwh_km*ev.total_distance/1000.0),"forecast_travel_kwh"::ev.assigned_travel_energy,"choice_wait_min"::ev.predicted_waiting_at_choice,"chosen_forecast_status"::ev.chosen_forecast_status];
    }
    action record_removed(string rid, string station_name, map data) {
        if rid in terminal_session_ids.keys { return nil; }
        terminal_session_ids[rid] <- true;
        session_events << ["request_id"::rid,"ev_id"::data["ev_id"],"event"::"cancelled",
        "time_min"::time/60.0,"station"::station_name,"requested_kwh"::data["requested_kwh"],
        "energy_kwh"::data["energy_kwh"],"waiting_min"::(data["state"]="waiting" ? max(0.0,time/60.0-float(data["arrival_min"])) : float(data["waiting_min"])),
        "travel_m"::data["travel_m"],"commit_min"::data["commit_min"],"eta_min"::data["eta_min"],"state"::"cancelled",
        "soc"::data["soc"],"travel_kwh"::data["travel_kwh"],"forecast_travel_kwh"::data["forecast_travel_kwh"],"choice_wait_min"::data["choice_wait_min"],"chosen_forecast_status"::data["chosen_forecast_status"]];
    }
    action record_event(elecar ev, string event_type) {
        if ranr_enabled and (event_type in ["cancelled","stranded","service_completed"] or (ranr_enabled and event_type in ["deferred","unserved","failed"])) {
            ranr_terminal_events << ["request_id"::ev.request_id,"key"::ev.ranr_demand_key,"at"::(event_type="service_completed" ? ev.service_finish : min(time/60.0,ev.request_time+ranr_deadline)),
                "status"::(event_type="service_completed" ? "completed" : (event_type="cancelled" ? "failed" : event_type)),"energy"::ev.delivered_energy,"waiting"::ev.waiting_time,"travel"::ev.ranr_travel_min];
        }
        if ev.request_id = "" { return nil; }
        if (event_type in ["cancelled","stranded","service_completed"] or (ranr_enabled and event_type in ["deferred","unserved","failed"])) {
            if ev.request_id in terminal_session_ids.keys { return nil; }
            terminal_session_ids[ev.request_id] <- true;
        }
        if event_type in ["request","deferred"] or (runtime_mode = "RECOMMENDATION_RUNTIME" and event_type in ["choice","en_route"]) {
            pending_session_data[ev.request_id] <- session_snapshot(ev);
        } else {
            remove key: ev.request_id from: pending_session_data;
        }
        session_events << ["request_id"::ev.request_id, "ev_id"::ev.name,
        "event"::event_type, "time_min"::(event_type = "service_completed" ? ev.service_finish : time / 60.0),
        "station"::(ev.current_station = nil ? "" : ev.current_station.name),
        "requested_kwh"::ev.requested_energy, "energy_kwh"::ev.delivered_energy, "waiting_min"::ev.waiting_time,
            "travel_m"::ev.total_distance,"commit_min"::ev.commit_time,"eta_min"::ev.assigned_eta, "state"::ev.session_state,
        "soc"::ev.battery_level,"travel_kwh"::(consumption_kwh_km*ev.total_distance/1000.0),"forecast_travel_kwh"::ev.assigned_travel_energy,"choice_wait_min"::ev.predicted_waiting_at_choice,"chosen_forecast_status"::ev.chosen_forecast_status];
    }
    reflex reconcile_pending_sessions {
        loop rid over: copy(pending_session_data.keys) {
            map data <- pending_session_data[rid];
            elecar ev <- elecar(data["ev"]);
            if ev = nil or dead(ev) {
                bool station_owned <- !empty(list(charging_station) where (rid in each.inbound_work.keys or rid in each.physical_sessions.keys));
                if !station_owned { do record_removed(rid,"",data); }
                ask charging_station { do withdraw_intention(rid); }
                remove key: rid from: pending_session_data;
            } else if !(ev.session_state in ["requested","deferred"] or (runtime_mode = "RECOMMENDATION_RUNTIME" and ev.session_state = "en_route")) {
                remove key: rid from: pending_session_data;
            }
        }
    }
    // Arrivals from the preceding movement interval precede this tick's service.
    reflex materialize_travel_arrivals when: !ranr_enabled {
        ask ev_population where (each.session_state = "en_route" and each.station_arrival_due >= 0.0 and each.station_arrival_due <= time / 60.0 + 1e-10) {
            do start_charging;
        }
    }
}

species charging_station parent: ranr_station_agent {
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
    bool compatible <- true;
    int installed_port_count -> port_250+port_180+port_150+port_60+port_30+port_11+
        length(charging_vehicles);
    float available_power_kw -> float(250*port_250+180*port_180+150*port_150+60*port_60+30*port_30+11*port_11);
    list<float> forecast_service(float epoch, int count) {
        list<float> capacities <- [];
        loop h from: 0 to: count - 1 {
            float capacity <- mock_capacity_per_bin;
            if mock_profile = "drop" and h >= 2 and h < 6 { capacity <- 0.0; }
            if mock_profile = "recovery" and h < 4 { capacity <- 0.0; }
            if mock_profile = "heterogeneous" { capacity <- capacity * (index mod 2 = 0 ? 2.0 : 0.5); }
            capacities << capacity;
        }
        return capacities;
    }
    map shadow_port_state(float forecast_epoch) {
        float tick_min <- step / 60.0;
        // Local copies only. Inbound is deliberately excluded from this oracle.
        list<float> rates <- [];
        list<float> free_at <- [];
        map<int,int> available_ports <- [250::port_250,180::port_180,150::port_150,60::port_60,30::port_30,11::port_11];
        loop rate over: CHARGING_RATES {
            assert available_ports[rate] >= 0;
            if available_ports[rate] > 0 {
                loop port_index from: 1 to: available_ports[rate] { rates << float(rate); free_at << 0.0; }
            }
        }
        loop session_data over: physical_sessions.values {
            if session_data["state"] != "charging" { continue; }
            elecar ev <- elecar(session_data["ev"]);
            float rate <- float(session_data["rate"]);
            assert rate > 0.0;
            float release_min <- 0.0;
            if ev != nil and !dead(ev) {
                if ev.completion_pending {
                    release_min <- tick_min * ceil(max(0.0,ev.service_finish-forecast_epoch) / tick_min - 1e-10);
                } else {
                    float energy <- max(0.0,min(ev.requested_energy-ev.delivered_energy,
                        (100.0-ev.battery_level)*battery_capacity_kwh/100.0));
                    release_min <- tick_min * max(1.0,ceil(60.0*energy/(charge_efficiency*rate)/tick_min - 1e-10));
                }
            }
            // A dead owner releases its port in the next reconciliation at this forecast_epoch.
            rates << rate; free_at << max(0.0,release_min);
        }
        loop ev over: waiting_queue {
            if dead(ev) or ev.session_state != "waiting" or empty(rates) { continue; }
            int selected <- 0;
            loop port_index from: 0 to: length(rates)-1 {
                if free_at[port_index] < free_at[selected]-1e-10 or
                    (abs(free_at[port_index]-free_at[selected]) <= 1e-10 and rates[port_index] > rates[selected]) { selected <- port_index; }
            }
            float energy <- max(0.0,min(ev.requested_energy-ev.delivered_energy,
                (100.0-ev.battery_level)*battery_capacity_kwh/100.0));
            float service_min <- 60.0*energy/(charge_efficiency*rates[selected]);
            free_at[selected] <- free_at[selected] + tick_min*max(1.0,ceil(service_min/tick_min - 1e-10));
        }
        return ["rates"::rates,"free_at"::free_at];
    }
    list<float> forecast_fixed_port(float forecast_epoch, int bins_count, float width_minutes) {
        assert bins_count > 0 and width_minutes > 0.0 and step > 0.0;
        assert reference_power_kw > 0.0 and reference_efficiency > 0.0 and charge_efficiency > 0.0;
        map state <- shadow_port_state(forecast_epoch);
        list<float> rates <- list<float>(state["rates"]);
        list<float> free_at <- list<float>(state["free_at"]);
        list<float> capacities <- [];
        loop h from: 0 to: bins_count-1 {
            float capacity <- 0.0;
            if !empty(rates) {
                loop port_index from: 0 to: length(rates)-1 {
                    float idle_min <- max(0.0,(h+1)*width_minutes-max(h*width_minutes,free_at[port_index]));
                    capacity <- capacity + idle_min*rates[port_index]*charge_efficiency/(reference_power_kw*reference_efficiency);
                }
            }
            capacities << capacity;
        }
        return capacities;
    }
    // Owned records survive external agent death: no dead-agent field dereference is required.
    map<string,map> physical_sessions <- [];
    map<string,map> inbound_data <- [];
    map<string,float> inbound_work <- [];
    map<string,float> inbound_eta <- [];
    map<string,elecar> inbound_ev <- [];

    // Actual arrivals only. No recommendation or choice is inserted here.
    list<map> observed_arrivals <- [];
    map<int,float> observed_bin_work <- [];
    list<charging_station> information_neighbors <- [];
    map<string,map> received_forecasts <- [];
    list<map> incoming_forecasts <- [];
    list<map> issued_forecasts <- [];
    list<map> forecast_evaluations <- [];
    list<map> pending_forecast_labels <- [];
    map<int,map<string,unknown>> correction_models <- [];
    map<string,unknown> advertised_waiting <- [];
    float next_forecast_min <- 0.0;
    int station_message_count <- 0;
    int station_message_bytes <- 0;
    list<map> communication_events <- [];
    map<string,unknown> last_wait_result <- [];
    map<string,map> intention_records <- []; // Audit only in v1, excluded from forecasting.
    map<string,map> waiting_cache <- [];
    map<string,map> replay_cache <- [];
    int exported_forecasts <- 0;
    int exported_forecast_evaluations <- 0;
    int exported_communications <- 0;
    int shadow_calls <- 0;
    int waiting_cache_hits <- 0;
    int peak_physical_queue <- 0;

    action report_intention(string rid, float eta, float demand) {
        intention_records[rid] <- ["eta"::eta,"workload"::demand,"issued_at"::time/60.0];
    }
    action withdraw_intention(string rid) { remove key: rid from: intention_records; }
    action observe_arrival(float at, float energy) {
        observed_arrivals << ["at"::at,"energy"::energy];
        int bin_index <- int(floor(at/observation_bin_minutes));
        float previous <- bin_index in observed_bin_work.keys ? observed_bin_work[bin_index] : 0.0;
        observed_bin_work[bin_index] <- previous + 60.0*energy/(reference_efficiency*reference_power_kw);

    }
    float bin_work(int bin_index) {
        return bin_index in observed_bin_work.keys ? observed_bin_work[bin_index] : 0.0;
    }
    float local_arrival_forecast(float issued) {
        int closed <- int(floor(issued/observation_bin_minutes+1e-10));
        int count <- min(observation_window,closed);
        if count = 0 { return 0.0; }
        float workload_sum <- 0.0;
        loop past_bin over: observed_bin_work.keys where (each >= closed-count and each < closed) {
            workload_sum <- workload_sum+observed_bin_work[past_bin];
        }
        return workload_sum/count;
    }
    action receive_available_forecasts(float at) {
        loop packet over: copy(incoming_forecasts) {
            if float(packet["deliver_at"]) > at+1e-10 { continue; }
            string sender <- string(packet["sender"]);
            if !(sender in received_forecasts.keys) or float(packet["issued_at"]) >= float(received_forecasts[sender]["issued_at"]) {
                received_forecasts[sender] <- packet;
            }
            communication_events << ["sender"::sender,"receiver"::name,"issued_at"::packet["issued_at"],"received_at"::at,
                "latency"::(at-float(packet["issued_at"])),"bytes"::length(string(packet))];
            remove packet from: incoming_forecasts;
        }
    }
    list<float> neighbor_features(float issued, int horizon, float local_value) {
        float neighboring <- 0.0; float age <- 0.0; int valid <- 0;
        loop other over: information_neighbors {
            if !(other.name in received_forecasts.keys) { continue; }
            map packet <- received_forecasts[other.name];
            if float(packet["issued_at"]) > issued+1e-10 or float(packet["deliver_at"]) > issued+1e-10 { continue; }
            list<float> values <- list<float>(packet["workload"]);
            int offset <- int(floor((issued-float(packet["issued_at"]))/observation_bin_minutes+1e-10));
            if offset+horizon >= length(values) { continue; }
            neighboring <- neighboring+values[offset+horizon];
            age <- age+(issued-float(packet["issued_at"]))/observation_bin_minutes;
            valid <- valid+1;
        }
        float mean_value <- valid > 0 ? neighboring/valid : 0.0;
        return [1.0,mean_value/forecast_feature_scale,(mean_value-local_value)/forecast_feature_scale,
            valid > 0 ? age/valid : 0.0,empty(information_neighbors) ? 1.0 : 1.0-float(valid)/length(information_neighbors),float(horizon)/forecast_horizon_bins];
    }
    float corrected_arrival(float issued, int horizon, float local_value) {
        if !neighbor_correction_enabled or waiting_forecast_mode != "B4-N" or !(horizon in correction_models.keys) { return local_value; }
        map<string,unknown> model_data <- correction_models[horizon];
        list<float> features <- neighbor_features(issued,horizon,local_value);
        if int(model_data["count"]) < max(ridge_min_samples,5*length(features)) { return local_value; }
        list<float> weights <- world.ridge_solution(list<float>(model_data["matrix"]),list<float>(model_data["target"]));
        float correction <- 0.0;
        loop j from: 0 to: length(features)-1 { correction <- correction+features[j]*weights[j]; }
        return max(0.0,local_value+correction*forecast_feature_scale);
    }
    action mature_forecasts(float issued) {
        int closed <- int(floor(issued/observation_bin_minutes+1e-10));
        loop label_data over: copy(pending_forecast_labels) {
            int target_bin <- int(label_data["bin"]);
            if target_bin >= closed { continue; }
            int horizon <- int(label_data["horizon"]);
            float actual <- bin_work(target_bin);
            float baseline <- float(label_data["local"]);
            forecast_evaluations << ["issued_at"::label_data["issued_at"],"observed_at"::issued,"horizon"::horizon,
                "actual"::actual,"local"::baseline,"corrected"::label_data["corrected"]];
            if waiting_forecast_mode != "B4-N" or !neighbor_correction_enabled {
                remove label_data from: pending_forecast_labels; continue;
            }
            list<float> features <- list<float>(label_data["features"]); int p <- length(features);
            if !(horizon in correction_models.keys) {
                list<float> a <- world.zero_vector(p*p); list<float> b <- world.zero_vector(p);
                loop j from: 0 to: p-1 { a[j*p+j] <- ridge_penalty; }
                map<string,unknown> fresh_model <- [];
                fresh_model["matrix"] <- a; fresh_model["target"] <- b; fresh_model["count"] <- 0;
                correction_models[horizon] <- fresh_model;
            }
            map<string,unknown> model_data <- correction_models[horizon];
            list<float> a <- list<float>(model_data["matrix"]); list<float> b <- list<float>(model_data["target"]);
            loop i from: 0 to: p-1 {
                b[i] <- b[i]+features[i]*(actual-baseline)/forecast_feature_scale;
                loop j from: 0 to: p-1 { a[i*p+j] <- a[i*p+j]+features[i]*features[j]; }
            }
            model_data["matrix"] <- a; model_data["target"] <- b; model_data["count"] <- int(model_data["count"])+1;
            correction_models[horizon] <- model_data;
            remove label_data from: pending_forecast_labels;
        }
    }
    action issue_station_forecast(float issued) {
        do mature_forecasts(issued);
        float oldest <- max(0.0,issued-observation_history_bins*observation_bin_minutes);
        observed_arrivals <- observed_arrivals where (float(each["at"]) >= oldest);
        loop bin_index over: copy(observed_bin_work.keys) {
            if (bin_index+1)*observation_bin_minutes < oldest { remove key: bin_index from: observed_bin_work; }
        }
        float local_value <- local_arrival_forecast(issued);
        list<float> values <- []; list<float> local_values <- [];
        int closed <- int(floor(issued/observation_bin_minutes+1e-10));
        loop h from: 0 to: forecast_horizon_bins-1 {
            float corrected <- corrected_arrival(issued,h,local_value);
            values << corrected; local_values << local_value;
            map<string,unknown> label_record <- [];
            label_record["issued_at"] <- issued; label_record["bin"] <- closed+h; label_record["horizon"] <- h;
            label_record["local"] <- local_value; label_record["corrected"] <- corrected;
            label_record["features"] <- neighbor_features(issued,h,local_value);
            pending_forecast_labels << label_record;
        }
        map<string,unknown> forecast_record <- [];
        forecast_record["issued_at"] <- issued; forecast_record["local"] <- local_values; forecast_record["workload"] <- values;
        issued_forecasts << forecast_record;
        waiting_cache <- []; replay_cache <- [];
        if waiting_forecast_mode = "B4-N" {
            map packet <- ["sender"::name,"sequence"::length(issued_forecasts),"issued_at"::issued,
                "deliver_at"::(issued+neighbor_delay_minutes),"bin_minutes"::observation_bin_minutes,
                "capacity"::forecast_fixed_port(issued,forecast_horizon_bins,observation_bin_minutes),"workload"::local_values,
                "unit"::"equivalent_reference_service_minutes","history_bins"::closed];
            int packet_bytes <- length(string(packet)); // ASCII field names/numeric values; GAMA logical serialization.
            loop other over: information_neighbors {
                other.incoming_forecasts << copy(packet);
                station_message_count <- station_message_count+1; station_message_bytes <- station_message_bytes+packet_bytes;
            }
        }
        // LIMITED_INFORMATION receives only an aggregate waiting curve, never the private queue.
        list<float> waiting_values <- []; list<string> waiting_statuses <- [];
        if information_mode = "LIMITED_INFORMATION" {
        loop minute_index from: 0 to: int(forecast_horizon_bins*observation_bin_minutes) {
            map prediction <- predict_waiting(issued,float(minute_index));
            waiting_values << float(prediction["waiting"]); waiting_statuses << string(prediction["status"]);
        }
        }
        advertised_waiting <- [];
        advertised_waiting["issued_at"] <- issued; advertised_waiting["received_at"] <- issued;
        advertised_waiting["waiting"] <- waiting_values; advertised_waiting["statuses"] <- waiting_statuses; advertised_waiting["resolution"] <- 1.0;
    }
    map replay_windows(float issued, int horizon) {
        string key_value <- string(int(floor(issued/observation_bin_minutes)))+":"+string(horizon)+":"+waiting_forecast_mode+":"+string(replay_similarity_threshold);
        if key_value in replay_cache.keys { return replay_cache[key_value]; }
        int closed <- int(floor(issued/observation_bin_minutes+1e-10));
        int observed_count <- length(observed_arrivals where (float(each["at"]) < closed*observation_bin_minutes));
        if closed < observation_min_bins or observed_count < observation_min_sessions {
            return ["status"::"cold_start","scenarios"::[],"error"::-1.0];
        }
        if closed < horizon { return ["status"::"insufficient_horizon","scenarios"::[],"error"::-1.0]; }
        float local_value <- local_arrival_forecast(issued); float scale <- max(1.0,local_value);
        list<float> predicted <- [];
        loop h from: 0 to: horizon-1 {
            float value <- local_value;
            if waiting_forecast_mode = "B4-N" and !empty(issued_forecasts) {
                map previous <- last(issued_forecasts);
                list<float> issued_values <- list<float>(previous["workload"]);
                int offset <- int(floor((issued-float(previous["issued_at"]))/observation_bin_minutes+1e-10));
                if offset+h < length(issued_values) { value <- issued_values[offset+h]; }
            }
            predicted << value;
        }
        list<map> ranked <- [];
        loop begin_bin from: max(0,closed-observation_history_bins) to: closed-horizon {
            float mismatch <- 0.0;
            loop h from: 0 to: horizon-1 { mismatch <- mismatch+((bin_work(begin_bin+h)-predicted[h])/scale)^2; }
            ranked << ["start"::begin_bin,"error"::sqrt(mismatch/horizon)];
        }
        ranked <- ranked sort_by float(each["error"]);
        float nearest_error <- float(ranked[0]["error"]);
        if replay_similarity_threshold < 0.0 { return ["status"::"ood_threshold_not_calibrated","scenarios"::[],"error"::nearest_error]; }
        list<map> accepted <- ranked where (float(each["error"]) <= replay_similarity_threshold);
        list<list<map>> scenarios <- [];
        if !empty(accepted) {
            loop k from: 0 to: min(replay_scenarios,length(accepted))-1 {
                float begin <- int(accepted[k]["start"])*observation_bin_minutes;
                float end_at <- begin+horizon*observation_bin_minutes;
                list<map> sessions <- [];
                loop historical over: observed_arrivals where (float(each["at"]) >= begin and float(each["at"]) < end_at) {
                    sessions << ["offset"::(float(historical["at"])-begin),"energy"::historical["energy"]];
                }
                scenarios << sessions;
            }
        }
        map result <- ["status"::(empty(scenarios) ? "out_of_distribution" : "replay"),"scenarios"::scenarios,"error"::nearest_error];
        replay_cache[key_value] <- result;
        return result;
    }
    float fluid_waiting(float issued, float eta_offset) {
        // Explicit fluid comparator: forecast arrivals at bin ends, never exact FIFO waiting.
        int probe_bin <- max(0,int(ceil(eta_offset/observation_bin_minutes))-1);
        int count <- max(forecast_horizon_bins,probe_bin+25);
        list<float> capacities <- forecast_fixed_port(issued,count,observation_bin_minutes);
        float backlog <- 0.0; float baseline <- local_arrival_forecast(issued);
        loop h from: 0 to: probe_bin {
            backlog <- baseline+max(0.0,backlog-capacities[h]);
        }
        if backlog <= 1e-10 { return 0.0; }
        float elapsed <- max(0.0,(probe_bin+1)*observation_bin_minutes-eta_offset);
        loop h from: probe_bin+1 to: count-1 {
            if capacities[h] >= backlog and capacities[h] > 0.0 {
                return elapsed+observation_bin_minutes*backlog/capacities[h];
            }
            backlog <- max(0.0,backlog-capacities[h]); elapsed <- elapsed+observation_bin_minutes;
        }
        return -1.0; // Horizon insufficient; never encode unknown waiting as zero.
    }
    map predict_waiting(float issued, float eta_offset) {
        assert eta_offset >= 0.0;
        string cache_key <- string(issued)+":"+string(eta_offset)+":"+waiting_forecast_mode+":"+waiting_estimator_mode+":"+ood_fallback_mode;
        if cache_key in waiting_cache.keys { waiting_cache_hits <- waiting_cache_hits+1; return waiting_cache[cache_key]; }
        map state <- shadow_port_state(issued);
        list<float> rates <- list<float>(state["rates"]); list<float> releases <- list<float>(state["free_at"]);
        float physical_wait <- world.discrete_shadow_wait(rates,releases,[],eta_offset);
        map result <- ["waiting"::physical_wait,"status"::"physical_only","error"::-1.0,"scenario_count"::0,"scenario_spread"::-1.0,"issued_at"::issued];
        if waiting_forecast_mode != "B3" {
            map replay <- replay_windows(issued,max(1,int(ceil(eta_offset/observation_bin_minutes))));
            list scenarios <- list(replay["scenarios"]);
            result["status"] <- replay["status"]; result["error"] <- replay["error"];
            result["scenario_count"] <- length(scenarios);
            if !empty(scenarios) {
                list<float> waits <- [];
                loop scenario over: scenarios {
                    waits << world.discrete_shadow_wait(rates,releases,list<map>(scenario),eta_offset);
                    shadow_calls <- shadow_calls+1;
                }
                result["waiting"] <- mean(waits); result["scenario_spread"] <- max(waits)-min(waits);
            }
        }
        if waiting_forecast_mode != "B3" and (waiting_estimator_mode = "fluid" or (ood_fallback_mode = "fluid" and string(result["status"]) = "out_of_distribution")) {
            float fluid <- fluid_waiting(issued,eta_offset);
            result["waiting"] <- fluid < 0.0 ? -1.0 : max(physical_wait,fluid);
            result["status"] <- fluid < 0.0 ? "fluid_horizon_exhausted" : (waiting_estimator_mode = "fluid" ? "fluid_approximation" : "ood_fluid_fallback");
            result["scenario_spread"] <- -1.0;
        }
        shadow_calls <- shadow_calls+1;
        waiting_cache[cache_key] <- result;
        last_wait_result <- result;
        return result;
    }

    aspect base { draw circle(40) color: #purple; }
    int find_available_port {
        map<int,int> ports <- [250::port_250,180::port_180,150::port_150,60::port_60,30::port_30,11::port_11];
        loop rate over: CHARGING_RATES { if ports[rate] > 0 { return rate; } }
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
    action remove_inbound(string rid) {
        remove key: rid from: inbound_work;
        remove key: rid from: inbound_eta;
        remove key: rid from: inbound_ev;
        remove key: rid from: inbound_data;
    }
    action reconcile_sessions {
        loop rid over: copy(inbound_work.keys) {
            elecar ev <- inbound_ev[rid];
            if ev = nil or dead(ev) {
                map data <- inbound_data[rid];
                if data != nil { string station_name <- name; ask world {do record_removed(rid,station_name,data);} }
                do remove_inbound(rid);
            }
        }
        loop rid over: copy(physical_sessions.keys) {
            map data <- physical_sessions[rid];
            elecar ev <- elecar(data["ev"]);
            if ev = nil or dead(ev) {
                if data["state"] = "charging" { do release_port(int(ranr_enabled ? data["port_rate"] : data["rate"])); }
                remove ev from: waiting_queue;
                remove ev from: charging_vehicles;
                remove key: rid from: physical_sessions;
                string station_name <- name;
                ask world {do record_removed(rid,station_name,data);}
            }
        }
    }
    action enqueue_arrival(elecar ev) {
        if ev = nil or dead(ev) or ev.current_station != self or !(ev.session_state in ["requested","assigned","en_route"]) { return nil; }
        if ev.arrival_time >= 0.0 { return nil; }
        if closest_intersection != nil and ev.location distance_to closest_intersection.location >= 2.0 { return nil; }
        if ev.station_arrival_due > time / 60.0 + 1e-10 { return nil; }
        do remove_inbound(ev.request_id);
        remove key: ev.request_id from: intention_records;
        waiting_cache <- [];
        // Reconcile forecast energy with actual arrival SOC only after removing inbound.
        // Frozen optimization coefficients remain in the exported batch snapshot.
        if charging_goal = "target_soc" and !ranr_enabled {
            ev.requested_energy <- max(0.0,(target_soc-ev.battery_level)*battery_capacity_kwh/100.0);
            ev.workload <- 60.0*ev.requested_energy/(reference_efficiency*reference_power_kw);
        }
        if ranr_calibrating and time/60.0>=ranr_warmup and ranr_energy_width>0.0 {
            float fraction <- ev.requested_energy/ranr_energy_width-floor(ev.requested_energy/ranr_energy_width);
            ranr_energy_observed_fractions << fraction;
        }
        ev.arrival_time <- time / 60.0;
        do observe_arrival(ev.arrival_time,ev.requested_energy);
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
        do reconcile_sessions;
        waiting_queue <- waiting_queue where (!dead(each) and each.session_state = "waiting");
        loop while: !empty(waiting_queue) and find_available_port() > 0 {
            elecar ev <- waiting_queue[0];
            remove ev from: waiting_queue;
            int rate <- find_available_port();
            do occupy_port(rate);
            charging_vehicles << ev;
            vehicle_charged <- vehicle_charged + 1;
            ev.charge_port_rate <- rate;
            ev.charge_rate <- ranr_enabled ? min(rate,int(ev.ranr_max_kw)) : rate;
            ev.is_charging <- true;
            ev.session_state <- "charging";
            ev.service_start <- time / 60.0;
            ev.ranr_last_integrated <- ev.service_start;
            ev.waiting_time <- ev.service_start - ev.arrival_time;
            total_waiting_time <- total_waiting_time + ev.waiting_time;
            physical_sessions[ev.request_id] <- world.session_snapshot(ev);
            ask world { do record_event(ev, "service_started"); }
        }
    }
    action cancel_session(elecar ev) {
        remove key: ev.request_id from: intention_records;
        waiting_cache <- [];
        do remove_inbound(ev.request_id);
        remove ev from: waiting_queue;
        if ev in charging_vehicles {
            remove ev from: charging_vehicles;
            do release_port(ranr_enabled ? ev.charge_port_rate : ev.charge_rate);
        }
        remove key: ev.request_id from: physical_sessions;
        if !ranr_enabled { do process_queue; }
    }
    float get_average_waiting_time { return vehicle_charged > 0 ? total_waiting_time / vehicle_charged : 0.0; }
    float get_average_charging_time { return served_customer > 0 ? total_charging_time / served_customer : 0.0; }
    float get_total_distance { return arrived_customer > 0 ? total_distance_travel / arrived_customer : 0.0; }
    bool check_in_queue(vehicle ev) { return ev in waiting_queue; }
    action ranr_capture(float at) {
        list<float> powers <- []; list<float> lower <- []; list<float> upper <- [];
        loop rate over: CHARGING_RATES {
            int count <- rate=250 ? port_250 : (rate=180 ? port_180 : (rate=150 ? port_150 : (rate=60 ? port_60 : (rate=30 ? port_30 : port_11))));
            if count>0 { loop j from: 1 to: count { powers << float(rate); lower << 0.0; upper << 0.0; } }
        }
        loop ev over: charging_vehicles {
            powers << float(ev.charge_port_rate);
            float remaining <- max(0.0,ev.requested_energy-ev.delivered_energy);
            float release <- min(max(0.0,ev.request_time+ranr_deadline-at),(step/60.0)*ceil((60.0*remaining/(charge_efficiency*ev.charge_rate))/(step/60.0)-1e-10));
            float lo <- ranr_snapshot_width>0.0 ? ranr_snapshot_width*floor(release/ranr_snapshot_width) : release;
            if ranr_calibrating and at>=ranr_warmup and ranr_snapshot_width>0.0 { ranr_release_observed_fractions << (release-lo)/ranr_snapshot_width; }
            lower << lo; upper << (ranr_snapshot_width>0.0 ? lo+ranr_snapshot_width : release);
        }
        list<map> queue <- [];
        loop ev over: waiting_queue {
            float energy <- max(0.0,ev.requested_energy-ev.delivered_energy);
            float lo <- ranr_energy_width>0.0 ? ranr_energy_width*floor(energy/ranr_energy_width) : energy;
            if ranr_calibrating and at>=ranr_warmup and ranr_energy_width>0.0 { ranr_energy_observed_fractions << (energy-lo)/ranr_energy_width; }
            queue << ["low"::lo,"high"::(ranr_energy_width>0.0 ? lo+ranr_energy_width : energy),"max_kw"::ev.ranr_max_kw,"deadline"::max(0.0,ev.request_time+ranr_deadline-at)];
        }
        ranr_local_snapshot <- ["sid"::ranr_sid,"issued"::at,"powers"::powers,"release_lo"::lower,"release_hi"::upper,"queue"::queue,"source"::"local"];
    }
    action ranr_advance_service(float at) {
        do reconcile_sessions;
        loop ev over: copy(charging_vehicles) {
            float elapsed <- max(0.0,min(at,ev.request_time+ranr_deadline)-ev.ranr_last_integrated);
            float remaining <- min(max(0.0,ev.requested_energy-ev.delivered_energy),max(0.0,(100.0-ev.battery_level)*battery_capacity_kwh/100.0));
            float energy <- min(remaining,charge_efficiency*ev.charge_rate*elapsed/60.0);
            float service_minutes <- 60.0*energy/(charge_efficiency*ev.charge_rate);
            float busy_duration <- max(0.0,min(ev.ranr_last_integrated+service_minutes,ranr_warmup+ranr_measure)-max(ev.ranr_last_integrated,ranr_warmup));
            ranr_busy_port_minutes <- ranr_busy_port_minutes+busy_duration;
            ranr_station_busy_minutes <- ranr_station_busy_minutes+busy_duration;
            ev.delivered_energy <- ev.delivered_energy+energy; ev.ranr_lifetime_charged_kwh <- ev.ranr_lifetime_charged_kwh+energy;
            ev.battery_level <- min(100.0,ev.battery_level+100.0*energy/battery_capacity_kwh);
            ev.charging_time <- ev.charging_time+service_minutes; power_consumed <- power_consumed+energy/charge_efficiency;
            if ev.requested_energy-ev.delivered_energy<=1e-9 {
                ev.service_finish <- ev.ranr_last_integrated+service_minutes; ev.completion_pending <- true;
                ask ev { do stop_charging; }
            }
            ev.ranr_last_integrated <- at;
        }
        ask waiting_queue { waiting_time <- max(0.0,at-arrival_time); }
    }
    action advance_service {
        waiting_cache <- [];
        do reconcile_sessions;
        // Finalize only once physical clock reaches the integrated interval end.
        ask copy(charging_vehicles) where (each.completion_pending and time/60.0 + 1e-10 >= each.service_finish) { do stop_charging; }
        do process_queue;
        ask waiting_queue { waiting_time <- max(0.0,time / 60.0 - arrival_time); }
        ask copy(charging_vehicles) where (!each.completion_pending) {
            float remaining <- min(requested_energy - delivered_energy, (100.0 - battery_level) * battery_capacity_kwh / 100.0);
            float energy <- min(max(0.0,remaining), charge_efficiency * charge_rate * step / 3600.0);
            float charge_seconds <- energy > 0.0 ? energy * 3600.0 / (charge_efficiency * charge_rate) : 0.0;
            delivered_energy <- delivered_energy + energy;
            battery_level <- min(100.0,battery_level + 100.0 * energy / battery_capacity_kwh);
            charging_time <- charging_time + charge_seconds / 60.0;
            myself.power_consumed <- myself.power_consumed + energy / charge_efficiency;
            if requested_energy - delivered_energy < 1e-9 or battery_level >= 100.0 - 1e-9 {
                // Events represent the end of the integration interval.
                service_finish <- time / 60.0 + charge_seconds / 60.0;
                completion_pending <- true;
            }
            myself.physical_sessions[request_id] <- world.session_snapshot(self);
        }
    }
    reflex service_tick when: !ranr_enabled { do advance_service; }

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
    int charge_rate <- 0;
    int charge_port_rate <- 0;
    float ranr_max_kw <- 120.0;
    float ranr_last_integrated <- 0.0;
    int ranr_demand_key <- -1;
    int ranr_demand_sequence <- 0;
    bool ranr_participating <- true;
    float ranr_travel_min <- 0.0;
    float ranr_private_compliance <- 0.8;
    map<string,unknown> ranr_result <- [];
    float waiting_time <- 0.0;
    float charging_time <- 0.0;
    float total_distance <- 0.0;
    bool charge_home <- false;
    int home_charge_day <- -1;
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
    list<charging_station> candidates <- [];
    list<float> candidate_eta <- [];
    list<float> candidate_distance <- [];
    list<float> candidate_energy <- [];
    list<float> candidate_requested_energy <- [];
    list<float> candidate_workload <- [];
    charging_station nearest_candidate;

    map<string,unknown> recommendation_result <- [];
    list<map> received_station_options <- [];
    int recommendation_version <- 0;
    charging_station recommended_station;
    charging_station actual_chosen_station;
    string personal_choice_method <- "minimax";
    list<float> personal_weights <- [];
    string trace_loaded_for_request <- "";
    list<map> choice_trace <- []; // Explicit supplied records; never fabricated.
    float predicted_waiting_at_choice <- -1.0;
    string chosen_forecast_status <- "";
    bool recommendation_followed <- false;
    list<map> rank_received_options(string normalization, string method, list<float> weights) {
        return world.rank_station_options(received_station_options,normalization,method,weights);
    }
    action apply_station_choice(charging_station destination_station, float predicted_eta, float predicted_energy, float energy_to_receive, float predicted_workload) {
        if !(session_state in ["requested","deferred"]) or destination_station = nil { return nil; }
        current_station <- destination_station;
        actual_chosen_station <- destination_station;
        commit_time <- time/60.0;
        total_distance <- 0.0;
        assigned_eta <- predicted_eta;
        assigned_travel_energy <- predicted_energy;
        if !ranr_enabled { requested_energy <- energy_to_receive; workload <- predicted_workload; }
        recommendation_followed <- destination_station = recommended_station;
        charge_home <- false;
        session_state <- "en_route";
        ask world { do record_event(myself,"choice"); do record_event(myself,"en_route"); }
        do compute_path graph: road_network target: destination_station.closest_intersection;
        if final_target = nil and location distance_to destination_station.closest_intersection.location < 2.0 { do start_charging; }
    }

    action begin_request {
        if needs_charging { return nil; }

        assert reference_efficiency > 0.0 and reference_efficiency <= 1.0 and reference_power_kw > 0.0;
        session_sequence <- session_sequence + 1;
        request_id <- ranr_enabled ? "ranr_"+ranr_demand_key : "req_" + session_sequence;
        session_state <- "requested";
        needs_charging <- true;
        charge_home <- false;
        request_time <- time / 60.0;
        commit_time <- -1.0;
        assigned_eta <- -1.0;
        assigned_travel_energy <- 0.0;
        arrival_time <- -1.0;
        station_arrival_due <- -1.0;
        service_start <- -1.0;
        service_finish <- -1.0;
        completion_pending <- false;
        if !ranr_enabled { requested_energy <- max(0.0,(target_soc - battery_level) * battery_capacity_kwh / 100.0); }
        delivered_energy <- 0.0;
        workload <- 60.0 * requested_energy / (reference_efficiency * reference_power_kw);
        waiting_time <- 0.0;
        charging_time <- 0.0;
        total_distance <- 0.0;
        if trace_loaded_for_request != "" { choice_trace <- []; trace_loaded_for_request <- ""; }
        chosen_forecast_status <- "";
        recommendation_result <- []; received_station_options <- []; recommended_station <- nil; actual_chosen_station <- nil;
        recommendation_version <- 0; predicted_waiting_at_choice <- -1.0; recommendation_followed <- false;
        temp_target <- target;
        ask world { do record_event(myself, "request"); }
    }
    action start_charging {
        // Compatibility entry point: arrival is idempotent, not a repeated port poll.
        if current_station = nil { return nil; }
        if session_state in ["completed","cancelled","stranded"] { return nil; }
        if request_id = "" {
            needs_charging <- false;
            do begin_request;
        }
        ask current_station { do enqueue_arrival(myself); }
    }
    action stop_charging {
        if session_state != "charging" or !completion_pending or time/60.0 + 1e-10 < service_finish { return nil; }
        session_state <- "completed";
        ask world { do record_event(myself, "service_completed"); }
        ask current_station {
            remove myself from: charging_vehicles;
            remove key: myself.request_id from: physical_sessions;
            do release_port(ranr_enabled ? myself.charge_port_rate : myself.charge_rate);
            served_customer <- served_customer + 1;
            total_charging_time <- total_charging_time + myself.charging_time;
            // Dispatch next EV on next tick, preventing service before interval end.
        }
        completion_pending <- false;
        is_charging <- false;
        needs_charging <- false;
        charge_rate <- 0;
        current_station <- nil;
    }
    action cancel_request(string reason) {
        if ranr_enabled and session_state in ["deferred","unserved","failed"] { return nil; }
        if session_state in ["cancelled","stranded","completed"] { return nil; }
        if current_station != nil { ask current_station { do cancel_session(myself); } }
        session_state <- reason;
        ask world { do record_event(myself, reason); }
        do unregister;
        final_target <- nil;
        needs_charging <- false;
        is_charging <- false;
        current_station <- nil;
        charge_rate <- 0;
    }
    reflex cease when: battery_level <= 0 and !is_charging and !ranr_stranded {
        do cancel_request("stranded");
        lost_car_location << location;
        batter_insufficient <- batter_insufficient + 1;
        do unregister; final_target <- nil; ranr_stranded <- true;
        if !ranr_enabled { do die; }
    }
    reflex move when: final_target != nil and battery_level > 0 and !is_charging {
        float movement_started <- machine_time;
        float previous_remaining <- remaining_trip_metres();
        max_speed <- (ele_car_speed #km / #h) * world.road_speed_factor(road(current_road));
        // A nearly empty battery cannot fund more distance than one native step.
        max_speed <- min(max_speed,battery_level*battery_capacity_kwh*10.0/(max(1e-12,consumption_kwh_km)*step));
        speed <- min(speed,max_speed);
        float saved_seed <- seed; int saved_usage <- rng_usage;
        if keyed_driving { seed <- world.mobility_rng_seed(mobility_id,cycle); }
        do drive;
        if keyed_driving { seed <- saved_seed; rng_usage <- saved_usage; }
        float travelled <- max(0.0,previous_remaining - remaining_trip_metres());
        ranr_lifetime_metres <- ranr_lifetime_metres+travelled;
        battery_level <- max(0.0,battery_level - 100.0 * consumption_kwh_km * travelled / (1000.0 * battery_capacity_kwh));
        if needs_charging { total_distance <- total_distance + travelled; if ranr_enabled { ranr_travel_min <- ranr_travel_min+step/60.0; } }
        if ranr_enabled { ranr_movement_ms <- ranr_movement_ms+machine_time-movement_started; }
        if needs_charging and current_station != nil and final_target = nil and travelled > 0.0 {
            station_arrival_due <- (time + step) / 60.0;
        }
        if final_target = nil { do unregister; }
        if runtime_mode in ["RECOMMENDATION_RUNTIME","RANR_RUNTIME"] and session_state = "en_route" { pending_session_data[request_id] <- world.session_snapshot(self); }
        shift_pt <- compute_position();
    }
    reflex request_charge when: !ranr_enabled and session_state in ["idle","completed"] and battery_level < 30.0 and !needs_charging and !is_charging {
        do begin_request;
    }
    reflex charge when: !ranr_enabled and current_station != nil and session_state = "en_route" and final_target = nil {
        if location distance_to current_station.closest_intersection.location < 2.0 {
            do start_charging;
        }
    }
    reflex charge_at_home when: !ranr_enabled and species(self) = private_ev and !needs_charging and !is_charging and day_end_time and home_charge_day != day_counter and home != nil and home.closest_intersection != nil and location distance_to home.closest_intersection.location < 2.0 and battery_level < 90.0 {
        home_charge_day <- day_counter;
        charge_home <- battery_level < 50.0 or mobility_flip(proba_charge_home,11);
    }
    reflex home_charging when: !ranr_enabled and charge_home {
        if day_start_time { charge_home <- false; }
        else {
            battery_level <- min(100.0,battery_level + 100.0 * charge_efficiency * home_power_kw * step / (3600.0 * battery_capacity_kwh));
            if battery_level >= 100.0 { charge_home <- false; }
        }
    }
}

species private_ev parent: elecar {
    init { if ranr_enabled { mobility_id <- 10000+index; } }
    image_file my_icon <- image_file("../includes/vinfast.png");

}

species taxi_ev parent: elecar {
    init { if ranr_enabled { mobility_id <- 20000+index; } }
    image_file my_icon <- image_file("../includes/xanhsm.png");

    reflex choose_path when: final_target = nil and !needs_charging and day_start_time and !ranr_inbound and !ranr_stranded{
        do select_target_path;
    }

    reflex entertainment_behavior when: is_entertainment_car {}
    reflex work_vehicle_behavior when: is_work_car {}

    action select_target_path {
        if temp_target = nil {
            target <- mobility_building(list(building),10);
        } else {
            target <- temp_target;
            temp_target <- nil;
        }

        write target.location;
        write target.closest_intersection;
        location <- (intersection closest_to self).location;
        do compute_path graph: road_network target: target.closest_intersection;
    }

    reflex go_home when: day_end_time and !needs_charging and !is_charging and final_target = nil and !ranr_inbound and !ranr_stranded {
        target <- home;
        do compute_path graph: road_network target: target.closest_intersection;
    }
}
