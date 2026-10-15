model ranr_runtime
import "Evaluation.gaml"

global {
    bool ranr_initialized <- false;
    bool ranr_done <- false;
    list<float> ranr_locked_environment <- [];
    string ranr_locked_design <- "";
    string ranr_locked_method <- "";
    int ranr_locked_samples <- 0;
    float ranr_locked_step <- 0.0;
    float ranr_locked_deadline <- 0.0;
    float ranr_locked_ev_speed <- 0.0;
    float ranr_locked_car_speed <- 0.0;
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
                else {
                    // Explicit cancellation reported to the original issuer by the EV.
                    charging_station issuer <- ranr_stations[ev.ranr_issuer];
                    ask issuer { do ranr_resolve(ev.ranr_token,"cancelled",at); }
                    if destination!=nil { ask destination { do cancel_session(ev); } }
                    do record_event(ev,"replan");
                    ask ev { if session_state="waiting" { ranr_previous_wait <- waiting_time; } do unregister; final_target <- nil; ranr_leg <- ranr_leg+1; session_state <- "requested"; current_station <- nil; arrival_time <- -1.0; }
                }
            }
        }
    }
    action ranr_abort(string reason) {
        ranr_error <- reason; ranr_done <- true;
        write "RANR_ERROR: "+reason;
        do pause;
    }
    action ranr_initialize {
        float started <- machine_time;
        ranr_master_seed <- float(seed);
        // Controlled runtime draws are keyed; the startup stream is finished.
        // GAMA setUsage(n) replays n draws, so restore an unused base stream.
        seed <- ranr_master_seed; rng_usage <- 0;
        if ranr_run_id="gui" { ranr_run_id <- "gui_"+string(machine_time)+"_"+string(int(seed)); ranr_output <- ranr_output+"/"+ranr_run_id; }
        assert ranr_enabled;
        assert ranr_private_frequency>=0.0 and ranr_taxi_frequency>=0.0;
        assert rush_extra_percent>=0.0 and rush_extra_percent<=30.0;
        assert ranr_soc_threshold>0.0 and ranr_soc_threshold<=target_soc and target_soc<=100.0;
        assert ranr_method in ["RANR-AW","No-P2P","No-Prediction","Fixed-Weights"];
        assert ranr_samples>0 and ranr_measure>0.0 and ranr_deadline>0.0 and step>0.0;
        if ranr_case in ["low_compliance","combined"] { ranr_true_compliance <- 0.2; }
        if ranr_case in ["delayed","combined"] { ranr_delay <- 5.0; }
        if ranr_case="combined" { ranr_loss <- 0.1; }
        assert ranr_temperature>0.0 and ranr_assumed_compliance>=0.0 and ranr_assumed_compliance<=1.0;
        assert ranr_true_defer>=0.0 and ranr_true_decline>=0.0 and ranr_true_defer+ranr_true_decline<=1.0;
        file destination <- new_folder(ranr_output); ranr_output <- destination.path;
        ranr_stations <- (list(charging_station) sort_by each.name);
        if ranr_station_events_file!="" { ranr_outage_schedule <- json_file(ranr_station_events_file).contents; loop outage over:ranr_outage_schedule { outage["applied"] <- false; assert int(outage["sid"])>=0 and int(outage["sid"])<11 and float(outage["factor"])>=0.0 and float(outage["factor"])<=1.0; } }
        assert length(ranr_stations)=11;
        loop sid from: 0 to: length(ranr_stations)-1 {
            charging_station station <- ranr_stations[sid]; station.ranr_sid <- sid;
            ask station { do ranr_capture(time/60.0); ranr_local_rate <- ranr_prior_rate; }
            map<string,unknown> prior <- ranr_record(["sid"::sid,"issued"::0.0,"powers"::copy(station.ranr_local_snapshot["powers"]),"release_lo"::zero_vector(station.installed_port_count),"release_hi"::zero_vector(station.installed_port_count),"queue"::[],"source"::"prior","operational"::true,"connectors"::["generic-public"]]);
            prior["source"] <- "prior"; prior["issued"] <- 0.0;
            ranr_public_priors << prior;
        }
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
                prior["operational"] <- true; prior["connectors"] <- copy(ranr_public_priors[sid]["connectors"]);
                ranr_public_priors[sid] <- prior; ranr_stations[sid].ranr_local_rate <- ranr_prior_rate;
            }
        } else {
            if !ranr_development { do ranr_abort("Train-only GAMA calibration required"); return nil; }
            ranr_release_fractions <- [0.1,0.3,0.5,0.7,0.9]; ranr_energy_fractions <- copy(ranr_release_fractions);
        }
        assert !empty(ranr_release_fractions) and min(ranr_release_fractions)>=0.0 and max(ranr_release_fractions)<=1.0;
        assert !empty(ranr_energy_fractions) and min(ranr_energy_fractions)>=0.0 and max(ranr_energy_fractions)<=1.0;
        save "request_id,issued_min,origin,energy_kwh,max_kw,initial_soc,participating\n" to: ranr_output+"/demand.csv" format: "text";
        save "request_id,issued_min,issuer,recommended,actual,weights,probabilities,estimates,entropy,state,costs,token,raw_features,normalized_features\n" to: ranr_output+"/recommendations.csv" format: "text";
        save "sender,receiver,sequence,issued_min,received_min,bytes,status\n" to: ranr_output+"/messages.csv" format: "text";
        save "request_id,terminal_record,time_min,energy_kwh,waiting_min,travel_m,token,leg\n" to: ranr_output+"/events.csv" format: "text";
        save "snapshot\n" to: ranr_output+"/calibration_snapshots.csv" format: "text";
        save "context\n" to: ranr_output+"/calibration_contexts.csv" format: "text";
        save "release_fraction,energy_fraction\n" to: ranr_output+"/calibration_fractions.csv" format: "text";
        do ranr_initialize_fleet;
        map<string,unknown> run_configuration <- ["backend"::"GAMA","run_id"::ranr_run_id,"method"::ranr_method,"case"::ranr_case,
            "seed"::seed,"initial_hour"::initial_hour,"step_seconds"::step,"warmup_minutes"::ranr_warmup,"measure_minutes"::ranr_measure,
            "deadline_minutes"::ranr_deadline,"scenarios"::ranr_samples,"development"::ranr_development,"gui_preview"::ranr_gui_preview_active,"environment_version"::ranr_environment_version,"calibrating"::ranr_calibrating,
            "initial_private_cars"::length(car),"initial_private_evs"::length(private_ev),"initial_electric_taxis"::length(taxi_ev),
            "calibration_source"::ranr_calibration_source,"parameters"::ranr_parameters,
            "private_frequency"::ranr_private_frequency,"taxi_frequency"::ranr_taxi_frequency,"soc_threshold"::ranr_soc_threshold,"target_soc"::target_soc,
            "base_opportunities_per_minute"::ranr_base_rate,"rush_enabled"::have_rush,"rush_extra_percent"::rush_extra_percent,
            "consumption_kwh_km"::consumption_kwh_km,"charge_efficiency"::charge_efficiency,"battery_capacity_kwh"::battery_capacity_kwh,"ev_speed_kmh"::ranr_ev_speed,"car_speed_kmh"::ranr_car_speed,"compliance"::ranr_true_compliance,"defer_probability"::ranr_true_defer,"decline_probability"::ranr_true_decline,"abandon_after_minutes"::ranr_abandon_after,"burst_size"::ranr_burst_size,"objective_version"::ranr_objective_version,"observation_version"::ranr_observation_version,
            "temperature"::ranr_temperature,"p2p_interval"::ranr_broadcast_period,"min_send_seconds"::(60.0*ranr_min_send),"stabilization"::ranr_stabilization,"behavior_case"::ranr_behavior_case,"failure_beta"::ranr_failure_beta,"energy_beta"::ranr_energy_beta,
            "delay_minutes"::ranr_delay,"packet_loss"::ranr_loss,"duplicate_probability"::ranr_duplicate_probability,"partition_begin"::ranr_partition_begin,"partition_end"::ranr_partition_end,"station_events"::ranr_station_events_file];
        save run_configuration to: ranr_output+"/configuration.json" format: "json";
        ranr_locked_method <- ranr_method;ranr_locked_samples <- ranr_samples;ranr_locked_step <- step;ranr_locked_deadline <- ranr_deadline; ranr_locked_ev_speed <- ele_car_speed; ranr_locked_car_speed <- car_speed;
        ranr_locked_environment <- [float(cars),float(privates),float(taxis),ranr_private_frequency,ranr_taxi_frequency,ranr_soc_threshold,target_soc,rush_extra_percent,float(have_rush),initial_hour,consumption_kwh_km,charge_efficiency];
        ranr_locked_design <- to_json([ranr_temperature,ranr_broadcast_period,ranr_min_send,ranr_delay,ranr_loss,ranr_duplicate_probability,ranr_partition_begin,ranr_partition_end,ranr_behavior_case,ranr_stabilization,ranr_failure_beta,ranr_energy_beta,ranr_true_decline,ranr_abandon_after,ranr_warmup,ranr_measure,ranr_horizon,ranr_ttl,ranr_station_events_file]);
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
        list<float> travel <- []; list<float> distances <- [];
        intersection origin <- intersection closest_to ev;
        float connector <- ev.location distance_to origin.location;
        if ev.current_road!=nil and ev.current_target!=nil { origin <- intersection(ev.current_target); connector <- ev.distance_to_current_target; }
        int origin_key <- origin.index;
        list<path> paths <- [];
        if origin_key in ranr_route_cache.keys { paths <- ranr_route_cache[origin_key]; ranr_route_hits <- ranr_route_hits+1; }
        else { loop station over:ranr_stations { paths << path_between(road_network,origin,station.closest_intersection); } ranr_route_cache[origin_key] <- paths; }
        loop sid from:0 to:length(paths)-1 {
            path route <- paths[sid]; float distance <- route=nil ? -1.0 : connector+sum(route.edges collect (road(each).shape.perimeter));
            bool feasible <- !(sid in ev.ranr_unavailable_sids) and distance>=0.0 and distance*consumption_kwh_km/1000.0+ranr_safety_soc*battery_capacity_kwh/100.0<=ev.battery_level*battery_capacity_kwh/100.0;
            travel << (feasible ? distance/(ranr_ev_speed/3.6)/60.0 : -1.0); distances << distance;
        }
        list<float> valid <- travel where (each>=0.0);
        int issuer <- ev.ranr_issuer>=0 ? ev.ranr_issuer : (empty(valid) ? 0 : travel index_of min(valid));
        ev.ranr_issuer <- issuer; ev.ranr_token <- string(issuer)+":"+string(ev.ranr_demand_key)+":"+string(ev.ranr_leg);
        ranr_route_ms <- ranr_route_ms+machine_time-started;
        return ranr_record(["key"::(ev.ranr_demand_key*3+ev.ranr_leg),"token"::ev.ranr_token,"at"::(time/60.0),"issuer"::issuer,"origin"::origin_key,"energy"::max(0.0,ev.requested_energy-ev.delivered_energy),"max_kw"::ev.ranr_max_kw,"travel"::travel,"distances"::distances,"connector"::ev.ranr_connector,"context"::ev.ranr_vehicle_kind,"remaining_deadline"::max(0.0,ev.request_time+ranr_deadline-time/60.0)]);
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
        if !(ev.request_id in ranr_demands.keys) {
            save ev.request_id+","+ev.request_time+","+request["origin"]+","+ev.requested_energy+","+ev.ranr_max_kw+","+ev.battery_level+","+ev.ranr_participating+"\n" to:ranr_output+"/demand.csv" format:"text" rewrite:false;
            ranr_demands[ev.request_id] <- ["key"::ev.ranr_demand_key,"at"::ev.request_time,"energy"::ev.requested_energy,"vehicle_id"::ev.mobility_id,"kind"::ev.ranr_vehicle_kind,"ev"::ev,"measured"::ev.ranr_measured];
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
        ranr_demands[ev.request_id]["route_energy_feasible"] <- sum(ranr_base(travel))>0.0;
        ranr_demands[ev.request_id]["replans"] <- ev.ranr_leg;
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
        if ranr_calibrating and ev.ranr_measured {
            map<string,unknown> context <- ["request_id"::ev.request_id,"token"::ev.ranr_token,"leg"::ev.ranr_leg,"vehicle_id"::ev.mobility_id,"kind"::ev.ranr_vehicle_kind,"chosen"::chosen,"issuer"::issuer,"travel"::travel,"energy"::request["energy"],"max_kw"::request["max_kw"],"participating"::participate,"recommended"::recommended,"context"::ev.ranr_vehicle_kind,"at"::at];
            ranr_context_buffer <- ranr_context_buffer+'"'+replace(to_json(context),'"','""')+'"\n';
        }

    }
    action ranr_finalize(elecar ev,string status,float at) {
        if ev.request_id in ranr_outcomes.keys { return nil; }
        map<string,unknown> demand <- ranr_demands[ev.request_id];
        if demand=nil { return nil; }
        at <- min(at,ev.request_time+ranr_deadline);
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
                rows <- rows+terminal_record["request_id"]+","+terminal_record["event"]+","+terminal_record["time_min"]+","+terminal_record["energy_kwh"]+","+terminal_record["waiting_min"]+","+terminal_record["travel_m"]+","+terminal_record["token"]+","+terminal_record["leg"]+"\n";
            }
            save rows to: ranr_output+"/events.csv" format:"text" rewrite:false; ranr_event_cursor <- length(session_events);
        }
    }
    action ranr_finish {
        do ranr_flush;
        list<map<string,unknown>> measured <- list(ranr_outcomes.values) where bool(each["measured"]);

        list<float> waits <- measured collect float(each["waiting_min"]);
        int installed <- int(sum(ranr_stations collect each.installed_port_count));
        list<map<string,unknown>> measured_opportunities <- ranr_opportunity_ledger where (bool(each["measured"]));
        map<string,unknown> components <- ranr_score(["results"::measured,"opportunities"::measured_opportunities,"peak"::ranr_peak_queue,"ports"::installed]);
        float objective <- float(components["objective"]);
        list<float> station_utilization <- ranr_stations collect (each.ranr_station_busy_minutes/(each.installed_port_count*ranr_measure));
        list<int> station_demand <- [];
        list<float> prediction_errors <- []; int matched <- 0; int recommended_count <- 0;
        loop sid from: 0 to: length(ranr_stations)-1 { station_demand << 0; }
        loop outcome over: measured {
            string rid <- string(outcome["request_id"]);
            if !(rid in ranr_decisions.keys) { continue; }
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
        float requested <- sum(measured collect float(each["requested_kwh"]));
        float delivered <- sum(measured collect float(each["delivered_kwh"]));
        map<string,unknown> metrics <- ["backend"::"GAMA","run_id"::ranr_run_id,"method"::ranr_method,"objective"::objective,"demand_count"::length(measured),
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
        metrics["objective_version"] <- ranr_objective_version;
        metrics["fitness_valid"] <- components["fitness_valid"];
        metrics["measurement_opportunity_count"] <- length(measured_opportunities);
        list<map<string,unknown>> completed <- measured where (each["status"]="completed");
        metrics["mean_completed_time_min"] <- empty(completed) ? 0.0 : mean(completed collect float(each["service_time_min"]));
        metrics["mean_time_per_opportunity_min"] <- sum(measured collect float(each["service_time_min"]))/max(1,length(measured_opportunities));
        metrics["mean_charging_min"] <- empty(measured) ? 0.0 : mean(measured collect float(each["charging_min"]));
        metrics["recommendation_latency_mean_ms"] <- empty(ranr_policy_latencies) ? 0.0 : mean(ranr_policy_latencies);
        metrics["recommendation_latency_p95_ms"] <- empty(ranr_policy_latencies) ? 0.0 : ranr_quantile(ranr_policy_latencies,0.95);
        metrics["recommendation_latency_max_ms"] <- empty(ranr_policy_latencies) ? 0.0 : max(ranr_policy_latencies);
        metrics["event_broadcasts"] <- ranr_event_broadcasts; metrics["periodic_broadcasts"] <- ranr_periodic_broadcasts;
        metrics["duplicate_packets"] <- sum(ranr_stations collect each.ranr_duplicate_packets);
        list<float> ages <- []; loop station over:ranr_stations { ages <- ages+station.ranr_received_ages; }
        metrics["received_information_age_min"] <- empty(ages) ? 0.0 : mean(ages);
        metrics["station_queue_pressure"] <- ranr_stations collect (float(each.peak_physical_queue)/max(1,each.installed_port_count));
        metrics["opportunity_count"] <- ranr_opportunity_count;
        metrics["activated_count"] <- ranr_activated_count;
        metrics["burst_shortfall"] <- ranr_burst_shortfall;
        metrics["inbound_created"] <- ranr_inbound_created; metrics["inbound_exited"] <- ranr_inbound_exited;
        metrics["persistent_vehicle_count"] <- length(ranr_city_vehicles where (!each.ranr_inbound));
        metrics["stranded_vehicle_count"] <- length(ranr_city_vehicles where each.ranr_stranded);
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
        list<map<string,unknown>> bursts <- [];
        list<float> burst_times <- remove_duplicates((measured_opportunities where (each["cause"]="burst")) collect float(each["at"]));
        loop burst_at over:burst_times {
            list<map<string,unknown>> opportunities <- measured_opportunities where (each["cause"]="burst" and float(each["at"])=burst_at);
            list<float> issued <- zero_vector(length(ranr_stations)); list<float> arrivals <- zero_vector(length(ranr_stations)); int unsuccessful <- 0;
            loop opportunity over:opportunities {
                string rid <- "ranr_"+opportunity["key"];
                if rid in ranr_decisions.keys {
                    map<string,unknown> decision <- ranr_decisions[rid]; int recommended <- int(decision["recommended"]); int chosen <- int(decision["chosen"]);
                    if recommended>=0 { issued[recommended] <- issued[recommended]+1.0; }
                    if chosen>=0 and !empty(session_events where (each["request_id"]=rid and each["event"]="arrival")) { arrivals[chosen] <- arrivals[chosen]+1.0; }
                    if rid in ranr_outcomes.keys and ranr_outcomes[rid]["status"]!="completed" { unsuccessful <- unsuccessful+1; }
                }
            }
            list<map<string,unknown>> pressure <- ranr_queue_history where (float(each["at"])>=burst_at and float(each["at"])<=burst_at+30.0);
            bursts << ["at"::burst_at,"opportunities"::length(opportunities),"activated"::length(opportunities where (each["status"]="activated")),"unsuccessful_requests"::unsuccessful,
                "issued_by_station"::issued,"arrivals_by_station"::arrivals,"issued_concentration"::(sum(issued)>0.0 ? sum(issued collect ((each/sum(issued))^2)) : 0.0),
                "arrival_concentration"::(sum(arrivals)>0.0 ? sum(arrivals collect ((each/sum(arrivals))^2)) : 0.0),"post_burst_peak_queue_30min"::(empty(pressure) ? 0 : max(pressure collect int(each["peak"])) )];
        }
        metrics["burst_diagnostics"] <- bursts;
        list<float> uncensored_errors <- []; list<float> tail_covered <- [];
        loop event_record over:session_events where (each["event"]="service_started") {
            string rid <- string(event_record["request_id"]);
            if !(rid in ranr_decisions.keys) or !(rid in ranr_demands.keys) or !bool(ranr_demands[rid]["measured"]) { continue; }
            map<string,unknown> decision <- ranr_decisions[rid]; int chosen <- int(decision["chosen"]); list<map<string,unknown>> estimates <- decision["estimates"];
            if chosen<0 or empty(estimates) { continue; }
            uncensored_errors << float(estimates[chosen]["mean"])+float(decision["known_waiting_at_decision"])-float(event_record["waiting_min"]);
            tail_covered << (float(event_record["waiting_min"])<=float(estimates[chosen]["p95"])+float(decision["known_waiting_at_decision"]) ? 1.0 : 0.0);
        }
        metrics["prediction_service_start_count"] <- length(uncensored_errors);
        metrics["prediction_service_start_mae_min"] <- empty(uncensored_errors) ? 0.0 : mean(uncensored_errors collect abs(each));
        metrics["prediction_p95_coverage"] <- empty(tail_covered) ? 0.0 : mean(tail_covered);
        save ranr_queue_history to:ranr_output+"/queue_history.json" format:"json";
        assert length(ranr_outcomes)=length(ranr_demands);
        list<map<string,unknown>> ledger <- [];
        loop opportunity over:ranr_opportunity_ledger {
            map<string,unknown> entry <- ranr_record(opportunity); string rid <- "ranr_"+opportunity["key"];
            if rid in ranr_outcomes.keys { entry["outcome"] <- ranr_outcomes[rid]; }
            ledger << entry;
        }
        save ledger to:ranr_output+"/opportunity_outcomes.json" format:"json";
        save list(ranr_outcomes.values) to: ranr_output+"/outcomes.json" format:"json";
        save metrics to: ranr_output+"/metrics.json" format:"json";
        save ["run_id"::ranr_run_id,"status"::"complete","backend"::"GAMA","finished_min"::(time/60.0),"outcome_count"::length(ranr_outcomes)] to: ranr_output+"/completion.json" format:"json";
        if ranr_collect_gui { ranr_collection_status <- ranr_gui_bridge("complete"); write ranr_collection_status; }
        ranr_done <- true;
        write "RANR_COMPLETE "+ranr_run_id;
        do pause;
    }
    reflex ranr_configuration_guard when: ranr_initialized and !ranr_done and !ranr_enabled {
        do ranr_abort("Enabling/disabling RANR requires restarting the experiment");
    }
    reflex ranr_tick when: ranr_enabled and !ranr_done {
        if !ranr_initialized { do ranr_initialize; if !ranr_initialized { return nil; } }
        if ranr_method!=ranr_locked_method or ranr_samples!=ranr_locked_samples or step!=ranr_locked_step or ranr_deadline!=ranr_locked_deadline or ele_car_speed!=ranr_locked_ev_speed or car_speed!=ranr_locked_car_speed or ranr_ev_speed!=ranr_locked_ev_speed or ranr_car_speed!=ranr_locked_car_speed { do ranr_abort("Method, samples, step, speeds and deadline require restarting the experiment"); return nil; }
        if ranr_locked_environment!=[float(cars),float(privates),float(taxis),ranr_private_frequency,ranr_taxi_frequency,ranr_soc_threshold,target_soc,rush_extra_percent,float(have_rush),initial_hour,consumption_kwh_km,charge_efficiency] { do ranr_abort("Fleet and physical configuration require restarting the experiment"); return nil; }
        if ranr_locked_design!=to_json([ranr_temperature,ranr_broadcast_period,ranr_min_send,ranr_delay,ranr_loss,ranr_duplicate_probability,ranr_partition_begin,ranr_partition_end,ranr_behavior_case,ranr_stabilization,ranr_failure_beta,ranr_energy_beta,ranr_true_decline,ranr_abandon_after,ranr_warmup,ranr_measure,ranr_horizon,ranr_ttl,ranr_station_events_file]) { do ranr_abort("Research configuration changed; restart required"); return nil; }
        float at <- time/60.0; ranr_tick_epoch <- ranr_tick_epoch+1;
        do ranr_apply_outages(at);
        float interval <- max(0.0,min(at,ranr_warmup+ranr_measure)-max(ranr_last_tick,ranr_warmup));
        // Busy-port time is integrated from actual service duration, including boundary clipping.
        ranr_last_tick <- at;
        loop service_station over:ranr_stations { ask service_station { do ranr_advance_service(at); } }
        loop terminal_record over: ranr_terminal_events {
            string rid <- string(terminal_record["request_id"]);
            if !(rid in ranr_outcomes.keys) and rid in ranr_demands.keys {
                map<string,unknown> demand <- ranr_demands[rid];
                ranr_outcomes[rid] <- ranr_outcome(demand,rid,string(terminal_record["status"]),float(terminal_record["at"]),float(terminal_record["energy"]),float(terminal_record["travel"]),float(terminal_record["waiting"]),float(terminal_record["charging"]));
            }
        }
        ranr_terminal_events <- [];
        loop ev over: copy(ev_population) {
            if !(ev.request_id in ranr_demands.keys) { continue; }
            if ev.request_id in ranr_outcomes.keys { continue; }
            if ev.session_state="completed" { do ranr_finalize(ev,"completed",ev.service_finish); }
            else if ev.session_state="stranded" { do ranr_finalize(ev,"stranded",at); }
            else if at>=ev.request_time+ranr_deadline {
                if ev.session_state="waiting" { ev.waiting_time <- ev.ranr_previous_wait+max(0.0,ev.request_time+ranr_deadline-ev.arrival_time); }
                ask ev { do cancel_request("deadline_missed"); } do ranr_finalize(ev,"deadline_missed",at);
            }
        }
        loop service_station over:ranr_stations { ask service_station { do process_queue; } }
        loop arriving_ev over:(ev_population where (each.session_state="en_route" and each.station_arrival_due>=0.0 and each.station_arrival_due<=at+1e-10)) sort_by each.ranr_demand_key { ask arriving_ev { do start_charging; } }
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
        if at>=ranr_warmup and at<ranr_warmup+ranr_measure { ranr_peak_queue <- max(ranr_peak_queue,max(ranr_stations collect length(each.waiting_queue))); }
        if at>=ranr_warmup and at>=ranr_next_queue_log {
            ranr_queue_history << ["at"::at,"queues"::(ranr_stations collect length(each.waiting_queue)),"peak"::max(ranr_stations collect length(each.waiting_queue))]; ranr_next_queue_log <- at+1.0;
        }
        if at>=ranr_next_flush { do ranr_flush; ranr_next_flush <- at+5.0; }
        if at>=ranr_warmup+ranr_measure+ranr_deadline { do ranr_finish; }
    }
}
