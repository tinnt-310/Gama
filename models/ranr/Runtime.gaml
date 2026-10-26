model ranr_runtime
import "Evaluation.gaml"

global {
    bool ranr_initialized <- false;
    bool ranr_done <- false;
    bool ranr_failed <- false;
    map<string,unknown> ranr_locked_settings <- [];
    float ranr_init_ms <- 0.0;
    float ranr_gis_ms <- 0.0;
    float ranr_next_flush <- 0.0;
    list<charging_station> ranr_stations <- [];
    list<map<string,unknown>> ranr_message_queue <- [];
    int ranr_tick_epoch <- 0;
    list<map<string,unknown>> ranr_outage_schedule <- [];
    int ranr_periodic_broadcasts <- 0;
    int ranr_event_broadcasts <- 0;
    list<map<string,unknown>> ranr_public_priors <- [];
    map<string,map<string,unknown>> ranr_demands <- [];
    map<string,map<string,unknown>> ranr_outcomes <- [];
    map<string,map<string,unknown>> ranr_decisions <- [];
    map<int,list<path>> ranr_route_cache <- [];
    int ranr_event_cursor <- 0;
    int ranr_message_count <- 0;
    int ranr_message_bytes <- 0;
    int ranr_received_count <- 0;
    int ranr_peak_queue <- 0;
    float ranr_queue_pressure <- 0.0;
    list<map<string,unknown>> ranr_queue_history <- [];
    float ranr_next_queue_log <- 0.0;
    float ranr_weight_h_sum <- 0.0;
    float ranr_entropy_sum <- 0.0;
    int ranr_measured_recommendations <- 0;
    int ranr_total_recommendations <- 0;
    float ranr_exposure_error_sum <- 0.0;
    float ranr_exposure_absolute_error_sum <- 0.0;
    int ranr_exposure_diagnostics <- 0;
    float ranr_last_tick <- 0.0;
    string ranr_recommendation_buffer <- "";
    string ranr_message_buffer <- "";
    string ranr_event_buffer <- "";
    string ranr_snapshot_buffer <- "";
    string ranr_context_buffer <- "";
    string ranr_fraction_buffer <- "";

    map<string,unknown> ranr_live_settings {
        // Snapshot inputs, not evolving populations/caches. Copy lists to detect in-place edits.
        // Rendering and icon size are intentionally adjustable while running.
        return ranr_record(["enabled"::ranr_enabled,"method"::ranr_method,"case"::ranr_case,
            "seed"::float(seed),"rng"::rng,"master_seed"::ranr_master_seed,"mobility_seed"::mobility_master_seed,
            "step_seconds"::step,"warmup_minutes"::ranr_warmup,"measure_minutes"::ranr_measure,"deadline_minutes"::ranr_deadline,
            "initial_hour"::initial_hour,"schedule_start_hour"::schedule_start_hour,
            "ev_speed_kmh"::ranr_ev_speed,"car_speed_kmh"::ranr_car_speed,"live_ev_speed"::ele_car_speed,"live_car_speed"::car_speed,
            "cars"::cars,"private_evs"::privates,"electric_taxis"::taxis,"rush_enabled"::have_rush,"rush_extra_percent"::rush_extra_percent,
            "consumption_kwh_km"::consumption_kwh_km,"charge_efficiency"::charge_efficiency,"battery_capacity_kwh"::battery_capacity_kwh,
            "compliance"::ranr_true_compliance,"defer_probability"::ranr_true_defer,"decline_probability"::ranr_true_decline,"abandon_after_minutes"::ranr_abandon_after,
            "delay_minutes"::ranr_delay,"packet_loss"::ranr_loss,"duplicate_probability"::ranr_duplicate_probability,"partition_begin"::ranr_partition_begin,"partition_end"::ranr_partition_end,
            "temperature"::ranr_temperature,"p2p_interval"::ranr_broadcast_period,"min_send_minutes"::ranr_min_send,
            "behavior_case"::ranr_behavior_case,"stabilization"::ranr_stabilization,"smoothing_alpha"::ranr_smoothing_alpha,"hysteresis_minutes"::ranr_hysteresis_minutes,
            "objective_config_hash"::ranr_objective_config_hash,"horizon"::ranr_horizon,"ttl"::ranr_ttl,"samples"::ranr_samples,
            "safety_soc"::ranr_safety_soc,"energy_retry_minutes"::ranr_energy_retry_minutes,"energy_retry_max_minutes"::ranr_energy_retry_max_minutes,"energy_urgent_soc"::ranr_energy_urgent_soc,"snapshot_width"::ranr_snapshot_width,"energy_width"::ranr_energy_width,
            "event_workload"::ranr_event_workload,"event_exposure"::ranr_event_exposure,
            "taper_soc"::copy(ranr_taper_soc),"taper_factors"::copy(ranr_taper_factors),"station_aggregate_power_kw"::copy(ranr_environment["station_aggregate_power_kw"]),"reference_power"::reference_power_kw,"reference_efficiency"::reference_efficiency,"lane_width"::lane_width,"keyed_driving"::keyed_driving,
            "run_id"::ranr_run_id,"output"::ranr_output,"parameter_file"::ranr_parameter_file,"calibration_file"::ranr_calibration_file,"station_events"::ranr_station_events_file,
            "parameters"::copy(ranr_parameters),"development"::ranr_development,"gui_preview"::ranr_gui_preview,"trace"::ranr_trace,
            "calibrating"::ranr_calibrating,"collect_gui"::ranr_collect_gui,"collection_seed"::ranr_collection_seed,
            "environment_version"::ranr_environment_version,"objective_version"::ranr_objective_version,"observation_version"::ranr_observation_version]);
    }
    action ranr_before_finish {
        // Entry-point models can flush their own statistics before completion is sealed.
    }
    action ranr_load_outage_schedule {
        ranr_outage_schedule <- [];
        if ranr_station_events_file="" { return nil; }
        // GAMA 1.9.3 wraps a top-level JSON array in the gama_contents entry.
        map<string,unknown> events_document <- json_file(ranr_station_events_file).contents;
        assert "gama_contents" in events_document.keys and events_document["gama_contents"] is list;
        ranr_outage_schedule <- list<map<string,unknown>>(events_document["gama_contents"]);
        // GUI loading also accepts historical unsorted files. Sort timestamps,
        // then retain original file order inside each timestamp explicitly.
        list<float> event_times <- remove_duplicates(ranr_outage_schedule collect float(each["at"])) sort_by each;
        list<map<string,unknown>> ordered_events <- [];
        loop event_at over:event_times {
            ordered_events <- ordered_events+(ranr_outage_schedule where (float(each["at"])=event_at));
        }
        ranr_outage_schedule <- ordered_events;
        loop outage over:ranr_outage_schedule {
            outage["applied"] <- false;
            assert int(outage["sid"])>=0 and int(outage["sid"])<11 and float(outage["at"])>=0.0 and float(outage["factor"])>=0.0 and float(outage["factor"])<=1.0;
        }
    }
    action ranr_apply_outages(float at) {
        loop outage over:ranr_outage_schedule where (!bool(each["applied"]) and float(each["at"])<=at) {
            charging_station station <- ranr_stations[int(outage["sid"])];
            // Settle preceding service interval before changing capacity.
            ask station { do ranr_advance_service(float(outage["at"])); ranr_operational <- bool(outage["operational"]); ranr_capacity_factor <- float(outage["factor"]); if "failed_ports" in outage.keys { ranr_failed_ports <- list<int>(outage["failed_ports"]); } ranr_critical <- true; ranr_dirty <- true; ranr_forecast_history <- []; }
            outage["applied"] <- true;
        }
    }
    action ranr_replan_events(float at) {
        loop ev over:ev_population where (each.needs_charging and each.session_state in ["en_route","waiting"]) {
            charging_station destination <- ev.current_station;
            bool observed_outage <- false;
            if destination!=nil {
                if ev.arrival_time>=0.0 or ev.location distance_to destination.closest_intersection.location<2.0 { observed_outage <- !destination.ranr_operational or !(ev.ranr_connector in destination.ranr_connectors) or destination.ranr_capacity_factor<=0.0; }
                else if ev.ranr_issuer>=0 {
                    ranr_station_agent issuer <- ranr_stations[ev.ranr_issuer];
                    if destination.ranr_sid in issuer.ranr_received.keys {
                        map<string,unknown> packet <- issuer.ranr_received[destination.ranr_sid];
                        map<string,unknown> snapshot <- packet["snapshot"];
                        observed_outage <- at-float(packet["issued"])<=ranr_ttl and "operational" in snapshot.keys and !bool(snapshot["operational"]);
                    }
                }
            }
            bool route_failed <- ev.session_state="en_route" and ev.final_target=nil and destination!=nil and ev.location distance_to destination.closest_intersection.location>=2.0;
            bool energy_unsafe <- ev.session_state="en_route" and ev.battery_level>0.0 and ev.remaining_trip_metres()*consumption_kwh_km/1000.0>ev.battery_level*battery_capacity_kwh/100.0;
            if ev.session_state="waiting" and ranr_abandon_after>=0.0 and at-ev.arrival_time>=ranr_abandon_after {
                ask ev { do cancel_request("abandoned"); } continue;
            }
            if observed_outage or route_failed or energy_unsafe {
                if destination!=nil and !(destination.ranr_sid in ev.ranr_unavailable_sids) { ev.ranr_unavailable_sids << destination.ranr_sid; }
                if ev.ranr_leg>=2 { ask ev { do cancel_request("no_feasible_station"); } }
                else if !ev.ranr_replan_pending {
                    ev.ranr_replan_pending <- true;
                    // Native compute_path snaps to its source vertex. Finish the current
                    // road segment before installing a replacement path, so no distance
                    // or battery energy is skipped by a mid-road replan.
                    if ev.session_state="waiting" or ev.current_road=nil or ev.location distance_to ranr_vehicle_origin(ev).location<1e-6 {
                        do ranr_commit_replan(ev,at);
                    }

                }
            }
        }
    }
    action ranr_commit_replan(elecar ev,float at) {
        charging_station issuer <- ranr_stations[ev.ranr_issuer];
        ask issuer { do ranr_resolve(ev.ranr_token,"cancelled",at); }
        if ev.current_station!=nil { ask ev.current_station { do cancel_session(ev); } }
        do record_event(ev,"replan");
        ask ev {
            if session_state="waiting" { ranr_previous_wait <- waiting_time; }
            do unregister; final_target <- nil; ranr_leg <- ranr_leg+1;
            session_state <- "requested"; current_station <- nil; arrival_time <- -1.0; station_arrival_due <- -1.0;
            ranr_replan_pending <- false; ranr_at_replan_node <- false;
        }
    }
    action ranr_abort(string reason) {
        ranr_error <- reason; ranr_failed <- true; ranr_done <- true;
        if ranr_collect_gui or ("collect_gui" in ranr_locked_settings.keys and bool(ranr_locked_settings["collect_gui"])) { ranr_collection_status <- "COLLECTION FAILED: "+reason; }
        write "RANR_ERROR: "+reason;
        string failure_output <- "output" in ranr_locked_settings.keys ? string(ranr_locked_settings["output"]) : ranr_output;
        string failure_run_id <- "run_id" in ranr_locked_settings.keys ? string(ranr_locked_settings["run_id"]) : ranr_run_id;
        if folder_exists(failure_output) {
            save ["run_id"::failure_run_id,"status"::"failed","reason"::reason,"at_min"::(time/60.0)] to:failure_output+"/failure.json" format:"json";
        }
        do pause;
    }
    action ranr_initialize {
        float started <- machine_time;
        ranr_master_seed <- mobility_seed; mobility_master_seed <- ranr_master_seed;
        // Native RNG is seeded once at startup; mobility never restores or reseeds it.
        if ranr_run_id="gui" { ranr_run_id <- "gui_"+string(machine_time)+"_"+string(int(seed)); ranr_output <- ranr_output+"/"+ranr_run_id; }
        assert ranr_enabled;
        assert rush_extra_percent>=0.0 and rush_extra_percent<=30.0;
        assert ranr_safety_soc>=0.0 and ranr_safety_soc<10.0 and ranr_energy_retry_minutes>0.0 and ranr_energy_retry_max_minutes>=ranr_energy_retry_minutes;
        assert ranr_method in ["RANR-AW","No-P2P","No-Prediction","Fixed-Weights"];
        assert ranr_samples>0 and ranr_measure>0.0 and ranr_deadline>0.0 and step>0.0;
        if ranr_case in ["low_compliance","combined"] { ranr_true_compliance <- 0.2; }
        if ranr_case in ["delayed","combined"] { ranr_delay <- 5.0; }
        if ranr_case="combined" { ranr_loss <- 0.1; }
        assert ranr_temperature>0.0 and ranr_assumed_compliance>=0.0 and ranr_assumed_compliance<=1.0;
        assert ranr_true_defer>=0.0 and ranr_true_decline>=0.0 and ranr_true_defer+ranr_true_decline<=1.0;
        file destination <- new_folder(ranr_output); ranr_output <- destination.path;
        ranr_stations <- (list(charging_station) sort_by each.name);
        do ranr_load_outage_schedule;
        assert length(ranr_stations)=11;
        loop sid from: 0 to: length(ranr_stations)-1 {
            charging_station station <- ranr_stations[sid]; station.ranr_sid <- sid;
            ask station { do ranr_capture(time/60.0); ranr_local_rate <- ranr_prior_rate; }
            map<string,unknown> prior <- ranr_record(["sid"::sid,"issued"::0.0,"powers"::copy(station.ranr_local_snapshot["powers"]),"release_lo"::zero_vector(station.installed_port_count),"release_hi"::zero_vector(station.installed_port_count),"queue"::[],"source"::"prior","operational"::true,"connectors"::["generic-public"]]);
            prior["source"] <- "prior"; prior["issued"] <- 0.0;
            prior["busy"] <- [];
            // Installed aggregate capacity is public metadata, independent of live peers/outages.
            map<string,unknown> public_limits <- ranr_environment["station_aggregate_power_kw"];
            prior["powers"] <- list<float>(station.ranr_port_catalog.values);
            prior["aggregate_kw"] <- station.ranr_station_limit_kw>=0.0 ? station.ranr_station_limit_kw : (public_limits contains_key station.name ? float(public_limits[station.name]) : sum(list<float>(prior["powers"])));
            ranr_public_priors << prior;
        }
        save (ranr_stations collect ["sid"::each.ranr_sid,"name"::each.name,"ports"::copy(each.ranr_port_catalog)]) to:ranr_output+"/station_inventory.json" format:"json";
        assert sum(ranr_stations collect each.installed_port_count)=125;
        assert abs(sum(ranr_stations collect sum(list<float>(each.ranr_local_snapshot["powers"]))) - 7195.0)<1e-8;
        loop source over: ranr_stations {
            loop target over: ranr_stations {
                path route <- path_between(road_network,source.closest_intersection,target.closest_intersection);
                assert route!=nil;
            }
        }
        do ranr_load_candidate;
        if !ranr_candidate_loaded { do ranr_abort(ranr_error); return nil; }
        if ranr_calibration_file="" and !ranr_development and file_exists("../outputs/gama_ranr/calibration/calibration.json") {
            ranr_calibration_file <- "../outputs/gama_ranr/calibration/calibration.json";
        }
        if ranr_calibration_file!="" {
            assert file_exists(ranr_calibration_file);
            map<string,unknown> calibration <- json_file(ranr_calibration_file).contents;
            assert string(calibration["objective_version"])=ranr_objective_version and string(calibration["objective_config_hash"])=ranr_objective_config_hash;
            assert string(calibration["observation_version"])=ranr_observation_version;
            assert string(calibration["backend"])="GAMA" and string(calibration["split"])="train" and string(calibration["environment_version"])=ranr_environment_version;
            ranr_release_fractions <- list<float>(calibration["release_fractions"]);
            ranr_energy_fractions <- list<float>(calibration["energy_fractions"]);
            ranr_energy_prior <- list<float>(calibration["energy_samples"]);
            ranr_eta_factors <- list<float>(calibration["eta_factors"]); assert !empty(ranr_eta_factors) and min(ranr_eta_factors)>0.0;
            ranr_prior_snapshots <- list(calibration["prior_snapshots"]);
            ranr_arrival_prior <- list(calibration["arrival_prior"]);
            ranr_arrival_probability <- float(calibration["arrival_probability"]);
            ranr_prior_rate <- float(calibration["request_rate"]); ranr_prior_background_rate <- float(calibration["background_rate"]); ranr_calibration_source <- "GAMA_train";
            if "response_prior" in calibration.keys { ranr_response_prior <- calibration["response_prior"]; }
            do ranr_index_calibration;
            loop sid from: 0 to: length(ranr_stations)-1 {
                list<map<string,unknown>> pool <- ranr_prior_snapshots where (int(each["sid"])=sid);
                assert !empty(pool);
                map<string,unknown> prior <- ranr_clone_snapshot(pool[0]); prior["source"] <- "prior"; prior["issued"] <- 0.0;
                // Historical outage samples are not proof of current infeasibility.
                prior["powers"] <- copy(ranr_public_priors[sid]["powers"]);
                prior["aggregate_kw"] <- ranr_public_priors[sid]["aggregate_kw"];
                prior["operational"] <- true; prior["connectors"] <- copy(ranr_public_priors[sid]["connectors"]);
                ranr_public_priors[sid] <- prior; ranr_stations[sid].ranr_local_rate <- ranr_prior_rate;
            }
        } else {
            if !ranr_development { do ranr_abort("Train-only GAMA calibration required"); return nil; }
            ranr_release_fractions <- [0.1,0.3,0.5,0.7,0.9]; ranr_energy_fractions <- copy(ranr_release_fractions);
        }
        assert !empty(ranr_release_fractions) and min(ranr_release_fractions)>=0.0 and max(ranr_release_fractions)<=1.0;
        assert !empty(ranr_energy_fractions) and min(ranr_energy_fractions)>=0.0 and max(ranr_energy_fractions)<=1.0;
        save "request_id,issued_min,origin,energy_kwh,max_kw,initial_soc,participating,intent_id,target_soc\n" to: ranr_output+"/demand.csv" format: "text";
        save "request_id,issued_min,issuer,recommended,actual,weights,probabilities,estimates,entropy,state,costs,token,raw_features,normalized_features\n" to: ranr_output+"/recommendations.csv" format: "text";
        save "sender,receiver,sequence,issued_min,received_min,bytes,status\n" to: ranr_output+"/messages.csv" format: "text";
        save "request_id,terminal_record,time_min,energy_kwh,waiting_min,travel_m,token,leg,station_sid,port_id,vehicle_id,soc,target_soc,intent_id,port_kw,ev_limit_kw\n" to: ranr_output+"/events.csv" format: "text";
        save "snapshot\n" to: ranr_output+"/calibration_snapshots.csv" format: "text";
        save "context\n" to: ranr_output+"/calibration_contexts.csv" format: "text";
        save "release_fraction,energy_fraction\n" to: ranr_output+"/calibration_fractions.csv" format: "text";
        save "request_id,at,reason,required_kwh,target_soc,soc\n" to:ranr_output+"/demand_energy_updates.csv" format:"text";
        do ranr_initialize_fleet;
        map<string,unknown> run_configuration <- ["backend"::"GAMA","run_id"::ranr_run_id,"method"::ranr_method,"case"::ranr_case,
            "seed"::seed,"initial_hour"::initial_hour,"step_seconds"::step,"warmup_minutes"::ranr_warmup,"measure_minutes"::ranr_measure,
            "deadline_minutes"::ranr_deadline,"scenarios"::ranr_samples,"development"::ranr_development,"gui_preview"::ranr_gui_preview_active,"environment_version"::ranr_environment_version,"calibrating"::ranr_calibrating,
            "initial_private_cars"::length(car),"initial_private_evs"::length(private_ev),"initial_electric_taxis"::length(taxi_ev),
            "calibration_source"::ranr_calibration_source,"parameters"::ranr_parameters,
            "demand_mechanism"::"soc_activity_intents","rush_enabled"::have_rush,"rush_extra_percent"::rush_extra_percent,
            "consumption_kwh_km"::consumption_kwh_km,"charge_efficiency"::charge_efficiency,"battery_capacity_kwh"::battery_capacity_kwh,"ev_speed_kmh"::ranr_ev_speed,"car_speed_kmh"::ranr_car_speed,"compliance"::ranr_true_compliance,"defer_probability"::ranr_true_defer,"decline_probability"::ranr_true_decline,"abandon_after_minutes"::ranr_abandon_after,"objective_version"::ranr_objective_version,"observation_version"::ranr_observation_version,
            "temperature"::ranr_temperature,"p2p_interval"::ranr_broadcast_period,"min_send_seconds"::(60.0*ranr_min_send),"stabilization"::ranr_stabilization,"behavior_case"::ranr_behavior_case,"objective_config_hash"::ranr_objective_config_hash,
            "delay_minutes"::ranr_delay,"packet_loss"::ranr_loss,"duplicate_probability"::ranr_duplicate_probability,"partition_begin"::ranr_partition_begin,"partition_end"::ranr_partition_end,"station_events"::ranr_station_events_file];
        save run_configuration to: ranr_output+"/configuration.json" format: "json";
        ranr_locked_settings <- ranr_live_settings();
        ranr_initialized <- true; ranr_init_ms <- machine_time-started;
    }
    action ranr_broadcast(charging_station sender,float at) {
        if ranr_method="No-P2P" { return nil; }
        float started <- machine_time;
        float workload <- ranr_snapshot_load(sender.ranr_local_snapshot)*60.0;
        float capacity <- sum(list<float>(sender.ranr_local_snapshot["powers"]));
        int count <- length(sender.ranr_local_exposure);
        bool critical <- sender.ranr_critical or workload>sender.ranr_last_workload+ranr_event_workload or (sender.ranr_last_capacity>=0.0 and abs(capacity-sender.ranr_last_capacity)>1e-9);
        bool heartbeat <- at>=sender.ranr_next_broadcast;
        bool event <- critical or abs(workload-sender.ranr_last_workload)>=ranr_event_workload or abs(count-sender.ranr_last_exposure)>=ranr_event_exposure or length(sender.ranr_resolutions)!=sender.ranr_last_resolution;
        if !(heartbeat or event) or at-sender.ranr_last_send<ranr_min_send-1e-10 { return nil; }
        sender.ranr_sequence <- sender.ranr_sequence+1;
        sender.ranr_local_requests <- sender.ranr_local_requests where (each>at-5.0);
        sender.ranr_local_rate <- 0.5*ranr_prior_rate+0.5*length(sender.ranr_local_requests)/5.0;
        loop key over:copy(sender.ranr_local_exposure.keys) { if float(sender.ranr_local_exposure[key]["expires"])<at { remove key:key from:sender.ranr_local_exposure; } }
        loop key over:copy(sender.ranr_resolutions.keys) { if float(sender.ranr_resolutions[key]["expires"])<at { remove key:key from:sender.ranr_resolutions; } }
        map<string,unknown> published <- ranr_clone_snapshot(sender.ranr_local_snapshot);
        // Published precision is identical for Proposed and No-Prediction.
        list<float> lo <- list<float>(published["release_lo"]); list<float> hi <- [];
        loop j from:0 to:length(lo)-1 { float value <- lo[j]; lo[j] <- ranr_snapshot_width>0.0 ? ranr_snapshot_width*floor(value/ranr_snapshot_width) : value; hi << (value<=0.0 ? 0.0 : lo[j]+ranr_snapshot_width); }
        published["release_lo"] <- lo; published["release_hi"] <- hi;
        map<string,unknown> packet <- ranr_record(["schema"::"peer-packet-3","sender"::sender.ranr_sid,"sequence"::sender.ranr_sequence,"issued"::at,"expires"::(at+ranr_ttl),"coverage"::at,
            "snapshot"::published,"exposure"::list(sender.ranr_local_exposure.values),"resolutions"::list(sender.ranr_resolutions.values),"rate"::sender.ranr_local_rate,"critical"::critical]);
        sender.ranr_last_send <- at; sender.ranr_next_broadcast <- at+ranr_broadcast_period; sender.ranr_last_workload <- workload; sender.ranr_last_capacity <- capacity;
        sender.ranr_last_exposure <- count; sender.ranr_last_resolution <- length(sender.ranr_resolutions); sender.ranr_dirty <- false; sender.ranr_critical <- false;
        if heartbeat { ranr_periodic_broadcasts <- ranr_periodic_broadcasts+1; } else { ranr_event_broadcasts <- ranr_event_broadcasts+1; }
        loop receiver over:ranr_stations where (each!=sender) {
            int entity <- sender.ranr_sid*100000+sender.ranr_sequence;
            int bytes <- length(to_json(packet)); ranr_message_count <- ranr_message_count+1; ranr_message_bytes <- ranr_message_bytes+bytes;
            bool partition <- at>=ranr_partition_begin and at<ranr_partition_end and sender.ranr_sid mod 2 != receiver.ranr_sid mod 2;
            if partition or ranr_uniform(401,entity,receiver.ranr_sid)<ranr_loss {
                ranr_message_buffer <- ranr_message_buffer+sender.ranr_sid+","+receiver.ranr_sid+","+sender.ranr_sequence+","+at+",-1,"+bytes+","+(partition ? "partition" : "lost")+"\n";
            } else {
                float deliver_at <- at-ranr_delay*ln(ranr_uniform(402,entity,receiver.ranr_sid));
                map<string,unknown> entry <- ranr_record(["receiver"::receiver.ranr_sid,"at"::deliver_at,"epoch"::ranr_tick_epoch,"packet"::ranr_clone_packet(packet),"bytes"::bytes]);
                ranr_message_queue << entry;
                if ranr_uniform(403,entity,receiver.ranr_sid)<ranr_duplicate_probability { ranr_message_queue << ranr_record(entry); ranr_message_count <- ranr_message_count+1; ranr_message_bytes <- ranr_message_bytes+bytes; }
            }
        }
        ranr_information_ms <- ranr_information_ms+machine_time-started;
    }
    action ranr_deliver(float at) {
        list<map<string,unknown>> delivered <- ranr_message_queue where (float(each["at"])<=at and int(each["epoch"])<ranr_tick_epoch);
        ranr_message_queue <- ranr_message_queue where (!(float(each["at"])<=at and int(each["epoch"])<ranr_tick_epoch));
        loop entry over: delivered sort_by float(each["at"]) {
            map<string,unknown> packet <- entry["packet"]; charging_station receiver <- ranr_stations[int(entry["receiver"])];
            ask receiver { do ranr_receive(packet,at); }
            ranr_received_count <- ranr_received_count+1;
            ranr_message_buffer <- ranr_message_buffer+packet["sender"]+","+entry["receiver"]+","+packet["sequence"]+","+packet["issued"]+","+at+","+entry["bytes"]+",delivered\n";
        }
    }
    map<string,unknown> ranr_request_context(elecar ev) {
        float started <- machine_time;
        list<float> travel <- []; list<float> distances <- []; list<float> arrival_energy <- [];
        intersection origin <- ranr_vehicle_origin(ev);
        float connector <- ev.location distance_to origin.location;
        if ev.current_road!=nil and ev.current_target!=nil { origin <- intersection(ev.current_target); connector <- ev.distance_to_current_target; }
        int origin_key <- origin.index;
        list<path> paths <- [];
        if (ranr_route_cache contains_key origin_key) { paths <- ranr_route_cache[origin_key]; ranr_route_hits <- ranr_route_hits+1; }
        else { loop station over:ranr_stations { paths << path_between(road_network,origin,station.closest_intersection); } ranr_route_cache[origin_key] <- paths; }
        loop sid from:0 to:length(paths)-1 {
            path route <- paths[sid]; float distance <- route=nil ? -1.0 : connector+sum(route.edges collect (road(each).shape.perimeter));
            bool feasible <- !(sid in ev.ranr_unavailable_sids) and distance>=0.0 and distance*consumption_kwh_km/1000.0+ranr_safety_soc*battery_capacity_kwh/100.0<=ev.battery_level*battery_capacity_kwh/100.0;
            travel << (feasible ? distance/(ranr_ev_speed/3.6)/60.0 : -1.0); distances << distance;
            arrival_energy << max(0.0,(ev.soc_session_target-ev.battery_level)*battery_capacity_kwh/100.0+max(0.0,distance)*consumption_kwh_km/1000.0);
        }
        list<float> valid <- travel where (each>=0.0);
        int issuer <- ev.ranr_issuer>=0 ? ev.ranr_issuer : (empty(valid) ? 0 : travel index_of min(valid));
        ev.ranr_issuer <- issuer; ev.ranr_token <- string(issuer)+":"+string(ev.ranr_demand_key)+":"+string(ev.ranr_leg);
        ranr_route_ms <- ranr_route_ms+machine_time-started;
        return ranr_record(["key"::(ev.ranr_demand_key*3+ev.ranr_leg),"token"::ev.ranr_token,"at"::(time/60.0),"issuer"::issuer,"origin"::origin_key,"energy"::max(0.0,ev.requested_energy-ev.delivered_energy),"max_kw"::ev.ranr_max_kw,"travel"::travel,"distances"::distances,"energy_by_station"::arrival_energy,"connector"::ev.ranr_connector,"context"::ev.ranr_vehicle_kind,"remaining_observation"::max(0.0,ranr_warmup+ranr_measure+ranr_deadline-time/60.0),"deadline"::ev.ranr_deadline_at]);
    }
    float ranr_driver_compliance(elecar ev,map<string,unknown> request) {
        if ranr_case in ["low_compliance","combined"] { return 0.2; }
        if ranr_behavior_case="high" { return 0.95; }
        if ranr_behavior_case="low" { return 0.2; }
        if ranr_behavior_case="misspecified" { return ev.ranr_vehicle_kind="taxi" ? 0.1 : 0.9; }
        if ranr_behavior_case="contextual" {
            list<float> valid <- list<float>(request["travel"]) where (each>=0.0);
            float travel <- empty(valid) ? 60.0 : min(valid);
            return max(0.1,min(0.95,ranr_true_compliance+(ev.ranr_vehicle_kind="taxi" ? -0.15 : 0.05)+(ev.battery_level<15.0 ? 0.1 : 0.0)-travel/200.0));
        }
        return ranr_true_compliance;
    }
    action ranr_process_request(elecar ev) {
        float at <- time/60.0;
        map<string,unknown> request <- ranr_request_context(ev);
        int issuer <- int(request["issuer"]); charging_station station <- ranr_stations[issuer];
        if !((ranr_demands contains_key ev.request_id)) {
            save ev.request_id+","+ev.request_time+","+request["origin"]+","+ev.requested_energy+","+ev.ranr_max_kw+","+ev.battery_level+","+ev.ranr_participating+","+ev.charging_intent_id+","+ev.soc_session_target+"\n" to:ranr_output+"/demand.csv" format:"text" rewrite:false;
            ranr_demands[ev.request_id] <- ranr_record(["key"::ev.ranr_demand_key,"at"::ev.request_time,"energy"::ev.requested_energy,"vehicle_id"::ev.mobility_id,"kind"::ev.ranr_vehicle_kind,"ev"::ev,"measured"::ev.ranr_measured,"intent_id"::ev.charging_intent_id]);
        }
        map<string,unknown> result <- [];
        map<string,unknown> observation <- [];
        bool participate <- ev.ranr_participating;
        if participate {
            ask station { do ranr_capture(at); }
            observation <- station.ranr_observe(at,ranr_public_priors);
            if ranr_calibrating {
                // Registered randomized measurement intervention, not a learned fifth policy.
                request["travel"] <- ranr_feasible_travel(request,observation);
                list<float> calibration_mass <- ranr_base(list<float>(request["travel"]));
                int offered <- sum(calibration_mass)>0.0 ? ranr_categorical(calibration_mass,ranr_uniform(202,ev.ranr_demand_key,ev.ranr_leg)) : -1;
                result <- ranr_record(["selected"::offered,"probabilities"::calibration_mass,"weights"::[0.2,0.2,0.2,0.2,0.2],"estimates"::[],"state"::[1.0,0.0,0.0,0.0,0.0]]);
                station.ranr_local_requests << at;
            } else { result <- station.ranr_recommend(request,observation); }
            if at>=ranr_warmup and at<ranr_warmup+ranr_measure {
                float expected_outstanding <- 0.0;
                loop cohort over: list(observation["exposure"]) { expected_outstanding <- expected_outstanding+int(cohort["count"])*sum(ranr_outstanding_mass(cohort,at)); }
                // Evaluator only: no EV identities or labels are fed back to policy.
                int actual_outstanding <- length(ev_population where (each.ranr_participating and each.session_state="en_route"));
                float error <- expected_outstanding-actual_outstanding;
                ranr_exposure_error_sum <- ranr_exposure_error_sum+error;
                ranr_exposure_absolute_error_sum <- ranr_exposure_absolute_error_sum+abs(error);
                ranr_exposure_diagnostics <- ranr_exposure_diagnostics+1;
            }
        } else { result <- ["selected"::-1,"weights"::[0.2,0.2,0.2,0.2,0.2],"probabilities"::ranr_base(list<float>(request["travel"])),"estimates"::[]]; }
        ev.ranr_result <- result;
        if participate { ranr_total_recommendations <- ranr_total_recommendations+1; }
        list<float> travel <- list<float>(request["travel"]); int recommended <- int(result["selected"]); int chosen <- -1;
        float outside_draw <- ranr_uniform(211,ev.ranr_demand_key,ev.ranr_leg);
        if outside_draw>=ranr_true_defer+ranr_true_decline {
            if recommended>=0 and ranr_uniform(212,ev.ranr_demand_key,ev.ranr_leg)<ranr_driver_compliance(ev,request) { chosen <- recommended; }
            else {
                list<float> preference_logits <- []; list<int> feasible <- [];
                loop sid from: 0 to: length(travel)-1 {
                    if travel[sid]>=0.0 { feasible << sid; preference_logits << -travel[sid]/15.0+0.5*ranr_normal(213,ev.ranr_demand_key,sid); }
                }
                if !empty(feasible) { chosen <- feasible[ranr_categorical(ranr_softmax(preference_logits),ranr_uniform(214,ev.ranr_demand_key,0))]; }
            }
        }
        map<string,unknown> updated_demand <- ranr_demands[ev.request_id];
        updated_demand["route_energy_feasible"] <- sum(ranr_base(travel))>0.0;
        updated_demand["replans"] <- ev.ranr_leg;
        ranr_demands[ev.request_id] <- updated_demand;
        ranr_decisions[ev.request_id] <- ["recommended"::recommended,"chosen"::chosen,"participating"::participate,"issuer"::issuer,"estimates"::result["estimates"],"known_waiting_at_decision"::ev.ranr_previous_wait];
        if chosen<0 { string terminal <- sum(ranr_base(travel))<=0.0 ? "no_feasible_station" : (outside_draw<ranr_true_defer ? "voluntary_deferred" : "declined");
            ask station { do ranr_resolve(ev.ranr_token,terminal,at); } ask ev { do cancel_request(terminal); } do ranr_finalize(ev,terminal,at); }
        else {
            charging_station chosen_station <- ranr_stations[chosen];
            ask ev {
                recommended_station <- recommended<0 ? nil : ranr_stations[recommended];
                do apply_station_choice(chosen_station,at+travel[chosen],list<float>(request["distances"])[chosen]*consumption_kwh_km/1000.0,requested_energy,workload);
            }
        }
        list<float> probability <- list<float>(result["probabilities"]);
        float entropy <- -sum(probability collect (each>0.0 ? each*ln(each) : 0.0));
        if participate and at>=ranr_warmup and at<ranr_warmup+ranr_measure {
            ranr_weight_h_sum <- ranr_weight_h_sum+list<float>(result["weights"])[3];
            ranr_entropy_sum <- ranr_entropy_sum+entropy;
            ranr_measured_recommendations <- ranr_measured_recommendations+1;
        }
        if ranr_trace {
            ranr_recommendation_buffer <- ranr_recommendation_buffer+ev.request_id+","+at+","+issuer+","+recommended+","+chosen+",\""+to_json(result["weights"])+"\",\""+to_json(probability)+"\",\""+replace(to_json(result["estimates"]),'"','""')+"\","+entropy+",\""+to_json("state" in result.keys ? result["state"] : [])+"\",\""+to_json("costs" in result.keys ? result["costs"] : [])+"\","+ev.ranr_token+",\""+to_json("raw_features" in result.keys ? result["raw_features"] : [])+"\",\""+to_json("normalized_features" in result.keys ? result["normalized_features"] : [])+"\"\n";
        }
        if ranr_calibrating and at>=ranr_warmup and at<ranr_warmup+ranr_measure {
            map<string,unknown> context <- ["request_id"::ev.request_id,"token"::ev.ranr_token,"leg"::ev.ranr_leg,"vehicle_id"::ev.mobility_id,"intent_id"::ev.charging_intent_id,"kind"::ev.ranr_vehicle_kind,"chosen"::chosen,"issuer"::issuer,"travel"::travel,"energy"::(chosen>=0 ? ev.requested_energy : request["energy"]),"energy_by_station"::request["energy_by_station"],"max_kw"::request["max_kw"],"participating"::participate,"recommended"::recommended,"context"::ev.ranr_vehicle_kind,"at"::at];
            ranr_context_buffer <- ranr_context_buffer+'"'+replace(to_json(context),'"','""')+'"\n';
        }

    }
    action ranr_session_energy_changed(elecar ev,string reason) {
        if (ranr_demands contains_key ev.request_id) {
            map<string,unknown> updated_demand <- ranr_demands[ev.request_id];
            updated_demand["energy"] <- ev.requested_energy;
            ranr_demands[ev.request_id] <- updated_demand;
        }
        save ev.request_id+","+time/60.0+","+reason+","+ev.requested_energy+","+ev.soc_session_target+","+ev.battery_level+"\n" to:ranr_output+"/demand_energy_updates.csv" format:"text" rewrite:false;
    }
    action ranr_finalize(elecar ev,string status,float at) {
        if (ranr_outcomes contains_key ev.request_id) { return nil; }
        map<string,unknown> demand <- ranr_demands[ev.request_id];
        if demand=nil { return nil; }
        float waiting <- ev.waiting_time;
        if ev.session_state="waiting" and ev.arrival_time>=0.0 { waiting <- max(waiting,ev.ranr_previous_wait+at-ev.arrival_time); }
        ranr_outcomes[ev.request_id] <- ranr_outcome(demand,ev.request_id,status,at,ev.delivered_energy,ev.ranr_travel_min,waiting,ev.ranr_charge_elapsed);
    }
    action ranr_flush {
        do ranr_flush_fleet;
        if ranr_recommendation_buffer!="" { save ranr_recommendation_buffer to: ranr_output+"/recommendations.csv" format:"text" rewrite:false; ranr_recommendation_buffer <- ""; }
        if ranr_message_buffer!="" { save ranr_message_buffer to: ranr_output+"/messages.csv" format:"text" rewrite:false; ranr_message_buffer <- ""; }
        if ranr_snapshot_buffer!="" { save ranr_snapshot_buffer to: ranr_output+"/calibration_snapshots.csv" format:"text" rewrite:false; ranr_snapshot_buffer <- ""; }
        if ranr_context_buffer!="" { save ranr_context_buffer to: ranr_output+"/calibration_contexts.csv" format:"text" rewrite:false; ranr_context_buffer <- ""; }
        if ranr_fraction_buffer!="" { save ranr_fraction_buffer to: ranr_output+"/calibration_fractions.csv" format:"text" rewrite:false; ranr_fraction_buffer <- ""; }
        if ranr_event_cursor<length(session_events) {
            string rows <- "";
            loop j from: ranr_event_cursor to: length(session_events)-1 {
                map<string,unknown> terminal_record <- session_events[j];
                rows <- rows+terminal_record["request_id"]+","+terminal_record["event"]+","+terminal_record["time_min"]+","+terminal_record["energy_kwh"]+","+terminal_record["waiting_min"]+","+terminal_record["travel_m"]+","+terminal_record["token"]+","+terminal_record["leg"]+","+terminal_record["station_sid"]+","+terminal_record["port_id"]+","+terminal_record["vehicle_id"]+","+terminal_record["soc"]+","+terminal_record["target_soc"]+","+terminal_record["intent_id"]+","+terminal_record["port_kw"]+","+terminal_record["ev_limit_kw"]+"\n";
            }
            save rows to: ranr_output+"/events.csv" format:"text" rewrite:false; ranr_event_cursor <- length(session_events);
        }
    }
    action ranr_finish {
        do ranr_finish_intents(time/60.0);
        do ranr_before_finish;
        do ranr_flush;
        list<map<string,unknown>> measured <- list(ranr_outcomes.values) where bool(each["measured"]);

        list<float> waits <- measured collect float(each["waiting_min"]);
        int installed <- int(sum(ranr_stations collect each.installed_port_count));
        list<map<string,unknown>> measured_intents <- list(ranr_intents.values) where (float(each["at"])>=ranr_warmup and float(each["at"])<ranr_warmup+ranr_measure);
        list<map<string,unknown>> intent_results <- list(ranr_intent_outcomes.values) where bool(each["measured"]);
        list<map<string,unknown>> mobility_cohort <- list(ranr_activity_outcomes.values) where (float(each["at"])>=ranr_warmup and float(each["at"])<ranr_warmup+ranr_measure);
        int mobility_unserved <- length(mobility_cohort where (each["status"]!="completed"));
        map<string,unknown> components <- ranr_score(["results"::list(ranr_intent_outcomes.values),"intents"::list(ranr_intents.values),
            "planned_ev_days"::ranr_planned_ev_days,"observation_end"::(time/60.0),"queue_pressure"::ranr_queue_pressure,
            "stranded_count"::length(ranr_stranded_ids),"mobility_unserved_count"::mobility_unserved]);
        list<float> station_utilization <- ranr_stations collect (each.ranr_station_busy_minutes/(each.installed_port_count*ranr_measure));
        list<int> station_demand <- [];
        list<float> prediction_errors <- []; int matched <- 0; int recommended_count <- 0;
        loop sid from: 0 to: length(ranr_stations)-1 { station_demand << 0; }
        loop outcome over: measured {
            string rid <- string(outcome["request_id"]);
            if !((ranr_decisions contains_key rid)) { continue; }
            map<string,unknown> decision <- ranr_decisions[rid]; int chosen <- int(decision["chosen"]);
            if chosen>=0 { station_demand[chosen] <- station_demand[chosen]+1; }
            if int(decision["recommended"])>=0 {
                recommended_count <- recommended_count+1;
                if chosen=int(decision["recommended"]) { matched <- matched+1; }
            }
            list<map<string,unknown>> estimates <- decision["estimates"];
            if chosen>=0 and !empty(estimates) and outcome["status"]="completed" {
                prediction_errors << float(estimates[chosen]["mean"])+float(decision["known_waiting_at_decision"])-float(outcome["waiting_min"]);
            }
        }
        float requested <- sum(intent_results collect float(each["requested_kwh"]));
        float delivered <- sum(intent_results collect float(each["delivered_kwh"]));
        map<string,unknown> metrics <- ["backend"::"GAMA","run_id"::ranr_run_id,"method"::ranr_method,"operational_objective"::components["operational_objective"],"demand_count"::length(measured),
            "all_demand_count"::length(ranr_demands),"all_outcome_count"::length(ranr_outcomes),"served_count"::length(measured where (each["status"]="completed")),
            "mean_travel_min"::(empty(measured) ? 0.0 : mean(measured collect float(each["travel_min"]))),"mean_wait_min"::(empty(waits) ? 0.0 : mean(waits)),"p95_wait_min"::(empty(waits) ? 0.0 : ranr_quantile(waits,0.95)),
            "mean_total_min"::(empty(measured) ? 0.0 : mean(measured collect (float(each["service_time_min"])))),"peak_queue"::ranr_peak_queue,
            "requested_kwh"::sum(measured collect float(each["requested_kwh"])),"delivered_kwh"::sum(measured collect float(each["delivered_kwh"])),
            "utilization"::(ranr_busy_port_minutes/(installed*ranr_measure)),"messages"::ranr_message_count,"communication_bytes"::ranr_message_bytes,
            "mean_weight_H"::(ranr_weight_h_sum/max(1,ranr_measured_recommendations)),
            "mean_active_weight_mass"::(ranr_method="No-Prediction" ? 1.0-ranr_weight_h_sum/max(1,ranr_measured_recommendations) : 1.0),
            "mean_recommendation_entropy"::(ranr_entropy_sum/max(1,ranr_measured_recommendations)),"received_messages"::ranr_received_count,"future_calls"::ranr_future_calls,"scenario_generations"::ranr_scenario_generations,"queue_calls"::ranr_queue_calls,
            "init_ms"::ranr_init_ms,"gis_ms"::ranr_gis_ms,"movement_ms"::ranr_movement_ms,"route_ms"::ranr_route_ms,"route_cache_hits"::ranr_route_hits,
            "prediction_ms"::ranr_prediction_ms,"externality_ms"::ranr_externality_ms,"policy_ms"::ranr_policy_ms,"information_ms"::ranr_information_ms];
        metrics <- ranr_record(metrics);
        metrics["objective_components"] <- components;
        metrics["objective_config_hash"] <- ranr_objective_config_hash;
        metrics["fitness_vector"] <- components["fitness_vector"];
        metrics["failure_reason"] <- components["failure_reason"];
        metrics["planned_ev_days"] <- ranr_planned_ev_days;
        metrics["mobility_planned_count"] <- length(mobility_cohort);
        metrics["mobility_completed_count"] <- length(mobility_cohort)-mobility_unserved;
        metrics["mobility_unserved_count"] <- mobility_unserved;
        metrics["not_on_time_count"] <- components["not_on_time_count"];
        metrics["unmet_kwh"] <- components["unmet_kwh"];
        metrics["queue_pressure"] <- ranr_queue_pressure;
        metrics["station_zero_capacity_events"] <- ranr_stations collect each.ranr_zero_capacity;
        metrics["maximum_physical_queue_length"] <- ranr_peak_queue;
        metrics["mean_completed_time_min"] <- components["mean_completion_min"];
        metrics["mean_wait_min"] <- components["mean_wait_min"];
        metrics["p95_wait_min"] <- components["p95_wait_min"];
        metrics["waiting_sample_count"] <- components["waiting_sample_count"];
        metrics["conditional_success_rate"] <- components["conditional_success_rate"];
        metrics["conditional_on_time_rate"] <- components["conditional_on_time_rate"];
        metrics["objective_version"] <- ranr_objective_version;
        metrics["fitness_valid"] <- components["fitness_valid"];
        metrics["measurement_intent_count"] <- length(measured_intents);
        list<map<string,unknown>> completed <- measured where (each["status"]="completed");
        metrics["mean_time_per_intent_min"] <- sum(intent_results collect float(each["service_time_min"]))/max(1,length(measured_intents));
        metrics["mean_charging_min"] <- empty(measured) ? 0.0 : mean(measured collect float(each["charging_min"]));
        metrics["recommendation_latency_mean_ms"] <- empty(ranr_policy_latencies) ? 0.0 : mean(ranr_policy_latencies);
        metrics["recommendation_latency_p95_ms"] <- empty(ranr_policy_latencies) ? 0.0 : ranr_quantile(ranr_policy_latencies,0.95);
        metrics["recommendation_latency_max_ms"] <- empty(ranr_policy_latencies) ? 0.0 : max(ranr_policy_latencies);
        metrics["event_broadcasts"] <- ranr_event_broadcasts; metrics["periodic_broadcasts"] <- ranr_periodic_broadcasts;
        metrics["duplicate_packets"] <- sum(ranr_stations collect each.ranr_duplicate_packets);
        list<float> ages <- []; loop station over:ranr_stations { ages <- ages+station.ranr_received_ages; }
        metrics["received_information_age_min"] <- empty(ages) ? 0.0 : mean(ages);
        metrics["station_queue_pressure"] <- ranr_stations collect each.ranr_peak_pressure;
        metrics["intent_count"] <- length(ranr_intents);
        metrics["intent_outcome_count"] <- length(ranr_intent_outcomes);
        metrics["recommendation_attempt_count"] <- ranr_total_recommendations;
        metrics["request_attempt_count"] <- length(ranr_attempts);
        metrics["retry_attempt_count"] <- length(ranr_attempts where (int(each["attempt"])>1));
        metrics["completed_intent_count"] <- length(intent_results where (each["status"]="completed"));
        metrics["unresolved_intent_count"] <- length(intent_results where (each["status"]="unresolved"));
        metrics["failed_intent_count"] <- length(intent_results where (each["status"]="failed"));
        metrics["intent_requested_kwh"] <- sum(intent_results collect float(each["requested_kwh"]));
        metrics["intent_delivered_kwh"] <- sum(intent_results collect float(each["delivered_kwh"]));
        metrics["inbound_created"] <- ranr_inbound_created; metrics["inbound_exited"] <- ranr_inbound_exited;
        metrics["persistent_vehicle_count"] <- length(ranr_city_vehicles where (!each.ranr_inbound));
        metrics["stranded_vehicle_count"] <- length(ranr_city_vehicles where each.ranr_stranded);
        metrics["energy_held_vehicle_count"] <- length(ranr_city_vehicles where each.ranr_energy_hold);
        metrics["low_soc_intent_count"] <- length(ranr_intents.values where (each["cause"]="low_soc"));
        metrics["trip_energy_intent_count"] <- length(ranr_intents.values where (each["cause"]="trip_energy"));
        metrics["shift_energy_intent_count"] <- length(ranr_intents.values where (each["cause"]="shift_energy"));
        metrics["empty_demand_run"] <- empty(measured);
        metrics["unserved_count"] <- length(measured where (each["status"]!="completed"));
        metrics["unserved_kwh"] <- max(0.0,requested-delivered);
        metrics["served_energy_fraction"] <- requested>0.0 ? delivered/requested : 0.0;
        metrics["recommendation_match_rate"] <- recommended_count>0 ? float(matched)/recommended_count : 0.0;
        metrics["recommendation_match_count"] <- matched; metrics["recommended_count"] <- recommended_count;
        metrics["prediction_completed_count"] <- length(prediction_errors);
        metrics["prediction_completed_bias_min"] <- empty(prediction_errors) ? 0.0 : mean(prediction_errors);
        metrics["prediction_completed_mae_min"] <- empty(prediction_errors) ? 0.0 : mean(prediction_errors collect abs(each));
        metrics["exposure_diagnostics_count"] <- ranr_exposure_diagnostics;
        metrics["known_exposure_outstanding_bias"] <- ranr_exposure_error_sum/max(1,ranr_exposure_diagnostics);
        metrics["known_exposure_outstanding_mae"] <- ranr_exposure_absolute_error_sum/max(1,ranr_exposure_diagnostics);
        metrics["station_utilization"] <- station_utilization;
        metrics["station_demand_count"] <- station_demand;
        metrics["load_balance_cv"] <- mean(station_utilization)>0.0 ? sqrt(mean(station_utilization collect ((each-mean(station_utilization))^2)))/mean(station_utilization) : 0.0;
        loop terminal_status over: ["completed","no_feasible_station","voluntary_deferred","declined","abandoned","deadline_missed","stranded"] { metrics[terminal_status+"_count"] <- length(measured where (each["status"]=terminal_status)); }
        metrics["deadline_missed_count"] <- length(intent_results where bool(each["deadline_missed"]));
        list<float> uncensored_errors <- []; list<float> tail_covered <- [];
        loop event_record over:session_events where (each["event"]="service_started") {
            string rid <- string(event_record["request_id"]);
            if !((ranr_decisions contains_key rid)) or !((ranr_demands contains_key rid)) or !bool(ranr_demands[rid]["measured"]) { continue; }
            map<string,unknown> decision <- ranr_decisions[rid]; int chosen <- int(decision["chosen"]); list<map<string,unknown>> estimates <- decision["estimates"];
            if chosen<0 or empty(estimates) { continue; }
            uncensored_errors << float(estimates[chosen]["mean"])+float(decision["known_waiting_at_decision"])-float(event_record["waiting_min"]);
            tail_covered << (float(event_record["waiting_min"])<=float(estimates[chosen]["p95"])+float(decision["known_waiting_at_decision"]) ? 1.0 : 0.0);
        }
        metrics["prediction_service_start_count"] <- length(uncensored_errors);
        metrics["prediction_service_start_mae_min"] <- empty(uncensored_errors) ? 0.0 : mean(uncensored_errors collect abs(each));
        metrics["prediction_p95_coverage"] <- empty(tail_covered) ? 0.0 : mean(tail_covered);
        loop kind_name over:["private","taxi"] {
            list<map<string,unknown>> group <- intent_results where (each["kind"]=kind_name);
            metrics[kind_name+"_intent_count"] <- length(group);
            metrics[kind_name+"_on_time_count"] <- length(group where bool(each["on_time"]));
            metrics[kind_name+"_completed_count"] <- length(group where (each["status"]="completed"));
            metrics[kind_name+"_conditional_success_rate"] <- empty(group) ? nil : float(length(group where (each["status"]="completed")))/length(group);
        }
        metrics["intents_per_planned_ev_day"] <- length(measured_intents)/max(1e-100,ranr_planned_ev_days);
        metrics["stranded_vehicle_count"] <- length(ranr_stranded_ids);
        save list(ranr_stranded_ids.keys) to:ranr_output+"/stranded_ev_ids.json" format:"json";
        save ranr_queue_history to:ranr_output+"/queue_history.json" format:"json";
        assert length(ranr_outcomes)=length(ranr_demands);
        assert length(ranr_intent_outcomes)=length(ranr_intents);
        save list(ranr_outcomes.values) to: ranr_output+"/outcomes.json" format:"json";
        save metrics to: ranr_output+"/metrics.json" format:"json";
        save ["run_id"::ranr_run_id,"status"::"complete","backend"::"GAMA","finished_min"::(time/60.0),"outcome_count"::length(ranr_outcomes)] to: ranr_output+"/completion.json" format:"json";
        if ranr_collect_gui { ranr_collection_status <- ranr_gui_bridge("complete"); write ranr_collection_status; }
        ranr_done <- true;
        write "RANR_COMPLETE "+ranr_run_id;
        do pause;
    }
    reflex ranr_configuration_guard when: ranr_initialized and !ranr_done {
        map<string,unknown> current <- ranr_live_settings();
        loop setting over:ranr_locked_settings.keys {
            if current[setting]!=ranr_locked_settings[setting] {
                do ranr_abort("Configuration changed: "+setting+"; restart required");
                return nil;
            }
        }
    }
    reflex ranr_tick when: ranr_enabled and !ranr_done {
        if !ranr_initialized { do ranr_initialize; if !ranr_initialized { return nil; } }
        float at <- time/60.0; ranr_tick_epoch <- ranr_tick_epoch+1;
        do ranr_apply_outages(at);
        float interval <- max(0.0,min(at,ranr_warmup+ranr_measure)-max(ranr_last_tick,ranr_warmup));
        // Busy-port time is integrated from actual service duration, including boundary clipping.
        ranr_last_tick <- at;
        loop service_station over:ranr_stations { ask service_station { do ranr_advance_service(at); } }
        loop terminal_record over: ranr_terminal_events {
            string rid <- string(terminal_record["request_id"]);
            if !((ranr_outcomes contains_key rid)) and (ranr_demands contains_key rid) {
                map<string,unknown> demand <- ranr_demands[rid];
                ranr_outcomes[rid] <- ranr_outcome(demand,rid,string(terminal_record["status"]),float(terminal_record["at"]),float(terminal_record["energy"]),float(terminal_record["travel"]),float(terminal_record["waiting"]),float(terminal_record["charging"]));
            }
        }
        ranr_terminal_events <- [];
        loop ev over: copy(ev_population) {
            if !((ranr_demands contains_key ev.request_id)) { continue; }
            if (ranr_outcomes contains_key ev.request_id) { continue; }
            if ev.session_state="completed" { do ranr_finalize(ev,"completed",ev.service_finish); }
            else if ev.session_state="stranded" { do ranr_finalize(ev,"stranded",at); }

        }
        loop service_station over:ranr_stations { ask service_station { do process_queue; } }
        // A replacement route can end at its source node without driving another
        // metre. Reconcile that physical arrival even when no movement callback
        // supplied a due time; enqueue_arrival still verifies station and position.
        loop arriving_ev over:(ev_population where (each.session_state="en_route" and each.current_station!=nil and each.final_target=nil and each.location distance_to each.current_station.closest_intersection.location<2.0 and each.station_arrival_due<=at+1e-10)) sort_by each.ranr_demand_key { ask arriving_ev { do start_charging; } }
        do ranr_deliver(at);
        do ranr_replan_events(at);
        do ranr_fleet_tick(at);
        loop ev over: ev_population where (each.session_state="requested") sort_by each.ranr_demand_key { do ranr_process_request(ev); }
        loop station over:ranr_stations {
            ask station { do ranr_capture(at); }
            bool sampling <- at>=station.ranr_next_broadcast;
            do ranr_broadcast(station,at);
            if ranr_calibrating and sampling and at>=ranr_warmup and at<ranr_warmup+ranr_measure {
                loop fraction over:station.ranr_release_observed_fractions { ranr_fraction_buffer <- ranr_fraction_buffer+fraction+",-1\n"; }
                loop fraction over:station.ranr_energy_observed_fractions { ranr_fraction_buffer <- ranr_fraction_buffer+"-1,"+fraction+"\n"; }
                station.ranr_release_observed_fractions <- []; station.ranr_energy_observed_fractions <- [];
                ranr_snapshot_buffer <- ranr_snapshot_buffer+'"'+replace(to_json(station.ranr_local_snapshot),'"','""')+'"\n';
            }
        }
        if at>=ranr_warmup {
            ranr_peak_queue <- max(ranr_peak_queue,max(ranr_stations collect length(each.waiting_queue)));
            ask ranr_stations { do ranr_measure_pressure; }
            ranr_queue_pressure <- max(ranr_queue_pressure,max(ranr_stations collect each.ranr_peak_pressure));
        }
        if at>=ranr_warmup and at>=ranr_next_queue_log {
            ranr_queue_history << ["at"::at,"queues"::(ranr_stations collect length(each.waiting_queue)),"peak"::max(ranr_stations collect length(each.waiting_queue)),"pressure"::(ranr_stations collect each.ranr_pressure),"zero_capacity"::(ranr_stations collect each.ranr_zero_capacity)]; ranr_next_queue_log <- at+1.0;
        }
        if at>=ranr_next_flush { do ranr_flush; ranr_next_flush <- at+5.0; }
        if at>=ranr_warmup+ranr_measure+ranr_deadline { do ranr_finish; }
    }
}
