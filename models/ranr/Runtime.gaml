model ranr_runtime
import "Fleet.gaml"

global {
    bool ranr_initialized <- false;
    bool ranr_done <- false;
    list<float> ranr_locked_environment <- [];
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
        bool gui_mode <- "gui_" in ranr_run_id or ranr_run_id="gui";
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
        assert ranr_true_defer>=0.0 and ranr_true_defer<=1.0;
        runtime_mode <- "RANR_RUNTIME"; coordination_enabled <- false;
        file destination <- new_folder(ranr_output); ranr_output <- destination.path;
        ranr_stations <- (list(charging_station) sort_by each.name);
        assert length(ranr_stations)=11;
        loop sid from: 0 to: length(ranr_stations)-1 {
            charging_station station <- ranr_stations[sid]; station.ranr_sid <- sid;
            ask station { do ranr_capture(time/60.0); ranr_local_rate <- ranr_prior_rate; }
            map<string,unknown> prior <- ranr_clone_snapshot(station.ranr_local_snapshot);
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
            ranr_prior_rate <- float(calibration["request_rate"]); ranr_prior_background_rate <- float(calibration["background_rate"]); ranr_calibration_source <- "GAMA_train";
            do ranr_index_calibration;
            loop sid from: 0 to: length(ranr_stations)-1 {
                list<map<string,unknown>> pool <- ranr_prior_snapshots where (int(each["sid"])=sid);
                assert !empty(pool);
                map<string,unknown> prior <- ranr_clone_snapshot(pool[0]); prior["source"] <- "prior"; prior["issued"] <- 0.0;
                ranr_public_priors[sid] <- prior; ranr_stations[sid].ranr_local_rate <- ranr_prior_rate;
            }
        } else {
            if !ranr_development { do ranr_abort("Train-only GAMA calibration required"); return nil; }
            ranr_release_fractions <- [0.1,0.3,0.5,0.7,0.9]; ranr_energy_fractions <- copy(ranr_release_fractions);
        }
        assert !empty(ranr_release_fractions) and min(ranr_release_fractions)>=0.0 and max(ranr_release_fractions)<=1.0;
        assert !empty(ranr_energy_fractions) and min(ranr_energy_fractions)>=0.0 and max(ranr_energy_fractions)<=1.0;
        save "request_id,issued_min,origin,energy_kwh,max_kw,initial_soc,participating\n" to: ranr_output+"/demand.csv" format: "text";
        save "request_id,issued_min,issuer,recommended,actual,weights,probabilities,estimates,entropy\n" to: ranr_output+"/recommendations.csv" format: "text";
        save "sender,receiver,sequence,issued_min,received_min,bytes,status\n" to: ranr_output+"/messages.csv" format: "text";
        save "request_id,terminal_record,time_min,energy_kwh,waiting_min,travel_m\n" to: ranr_output+"/events.csv" format: "text";
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
            "consumption_kwh_km"::consumption_kwh_km,"charge_efficiency"::charge_efficiency,"battery_capacity_kwh"::battery_capacity_kwh,"ev_speed_kmh"::ranr_ev_speed,"car_speed_kmh"::ranr_car_speed,"compliance"::ranr_true_compliance,"defer_probability"::ranr_true_defer,"burst_size"::ranr_burst_size];
        save run_configuration to: ranr_output+"/configuration.json" format: "json";
        ranr_locked_method <- ranr_method;ranr_locked_samples <- ranr_samples;ranr_locked_step <- step;ranr_locked_deadline <- ranr_deadline; ranr_locked_ev_speed <- ele_car_speed; ranr_locked_car_speed <- car_speed;
        ranr_locked_environment <- [float(cars),float(privates),float(taxis),ranr_private_frequency,ranr_taxi_frequency,ranr_soc_threshold,target_soc,rush_extra_percent,float(have_rush),initial_hour,consumption_kwh_km,charge_efficiency];
        ranr_initialized <- true; ranr_init_ms <- machine_time-started;
    }
    action ranr_broadcast(charging_station sender,float at) {
        if ranr_method="No-P2P" { return nil; }
        float started <- machine_time;
        sender.ranr_sequence <- sender.ranr_sequence+1;
        sender.ranr_local_requests <- sender.ranr_local_requests where (each>at-5.0);
        sender.ranr_local_rate <- 0.5*ranr_prior_rate+0.5*length(sender.ranr_local_requests)/5.0;
        loop key over: copy(sender.ranr_local_exposure.keys) {
            if float(sender.ranr_local_exposure[key]["expires"])<at { remove key: key from: sender.ranr_local_exposure; }
        }
        map<string,unknown> packet <- ["sender"::sender.ranr_sid,"sequence"::sender.ranr_sequence,"issued"::at,
            "snapshot"::copy(sender.ranr_local_snapshot),"exposure"::copy(list(sender.ranr_local_exposure.values)),"rate"::sender.ranr_local_rate];
        loop receiver over: ranr_stations where (each!=sender) {
            int entity <- sender.ranr_sid*100000+sender.ranr_sequence;
            int bytes <- length(to_json(packet)); ranr_message_count <- ranr_message_count+1; ranr_message_bytes <- ranr_message_bytes+bytes;
            if ranr_uniform(401,entity,receiver.ranr_sid)<ranr_loss {
                ranr_message_buffer <- ranr_message_buffer+sender.ranr_sid+","+receiver.ranr_sid+","+sender.ranr_sequence+","+at+",-1,"+bytes+",lost\n";
            } else {
                float deliver_at <- at-ranr_delay*ln(ranr_uniform(402,entity,receiver.ranr_sid));
                ranr_message_queue << ["receiver"::receiver.ranr_sid,"at"::deliver_at,"packet"::packet,"bytes"::bytes];
            }
        }
        ranr_information_ms <- ranr_information_ms+machine_time-started;
    }
    action ranr_deliver(float at) {
        list<map<string,unknown>> delivered <- ranr_message_queue where (float(each["at"])<=at);
        ranr_message_queue <- ranr_message_queue where (float(each["at"])>at);
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
        int origin_key <- origin.index;
        list<path> paths <- [];
        if origin_key in ranr_route_cache.keys { paths <- ranr_route_cache[origin_key]; ranr_route_hits <- ranr_route_hits+1; }
        else {
            loop station over: ranr_stations { paths << path_between(road_network,origin,station.closest_intersection); }
            ranr_route_cache[origin_key] <- paths;
        }
        loop sid from: 0 to: length(paths)-1 {
            path route <- paths[sid];
            if route=nil { travel << -1.0; distances << -1.0; continue; }
            float distance <- sum(route.edges collect (road(each).shape.perimeter));
            float travel_minutes <- sum(route.edges collect (road(each).shape.perimeter/(max(1e-6,ele_car_speed/3.6)*world.road_speed_factor(road(each)))/60.0));
            list<float> forecast <- route_forecast(ev,ranr_stations[sid]); distance <- forecast[0]; travel_minutes <- forecast[1];
            bool feasible <- distance>=0.0 and distance*consumption_kwh_km/1000.0+3.0 <= ev.battery_level*battery_capacity_kwh/100.0;
            travel << (feasible ? travel_minutes : -1.0); distances << distance;
        }
        list<float> valid <- travel where (each>=0.0);
        int issuer <- empty(valid) ? 0 : travel index_of min(valid);
        ranr_route_ms <- ranr_route_ms+machine_time-started;
        return ["key"::ev.ranr_demand_key,"at"::(time/60.0),"issuer"::issuer,"origin"::origin_key,"energy"::ev.requested_energy,"max_kw"::ev.ranr_max_kw,"travel"::travel,"distances"::distances];
    }
    action ranr_process_request(elecar ev) {
        float at <- time/60.0;
        do ranr_deliver(at);
        map<string,unknown> request <- ranr_request_context(ev);
        int issuer <- int(request["issuer"]); charging_station station <- ranr_stations[issuer];
        if !(ev.request_id in ranr_demands.keys) {
            save ev.request_id+","+ev.request_time+","+request["origin"]+","+ev.requested_energy+","+ev.ranr_max_kw+","+ev.battery_level+","+ev.ranr_participating+"\n" to:ranr_output+"/demand.csv" format:"text" rewrite:false;
            ranr_demands[ev.request_id] <- ["key"::ev.ranr_demand_key,"at"::ev.request_time,"energy"::ev.requested_energy,"vehicle_id"::ev.mobility_id,"kind"::ev.ranr_vehicle_kind,"ev"::ev,"measured"::(ev.request_time>=ranr_warmup and ev.request_time<ranr_warmup+ranr_measure)];
        }
        map<string,unknown> result <- [];
        map<string,unknown> observation <- [];
        bool participate <- ev.ranr_participating;
        if participate and !ranr_calibrating {
            ask station { do ranr_capture(at); }
            observation <- station.ranr_observe(at,ranr_public_priors);
            result <- station.ranr_recommend(request,observation);
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
        if participate and !ranr_calibrating { ranr_total_recommendations <- ranr_total_recommendations+1; }
        list<float> travel <- list<float>(request["travel"]); int recommended <- int(result["selected"]); int chosen <- -1;
        if ranr_uniform(211,ev.ranr_demand_key,0)>=ranr_true_defer {
            if recommended>=0 and ranr_uniform(212,ev.ranr_demand_key,0)<ranr_true_compliance { chosen <- recommended; }
            else {
                list<float> preference_logits <- []; list<int> feasible <- [];
                loop sid from: 0 to: length(travel)-1 {
                    if travel[sid]>=0.0 { feasible << sid; preference_logits << -travel[sid]/15.0+0.5*ranr_normal(213,ev.ranr_demand_key,sid); }
                }
                if !empty(feasible) { chosen <- feasible[ranr_categorical(ranr_softmax(preference_logits),ranr_uniform(214,ev.ranr_demand_key,0))]; }
            }
        }
        ranr_decisions[ev.request_id] <- ["recommended"::recommended,"chosen"::chosen,"participating"::participate,"issuer"::issuer,"estimates"::result["estimates"]];
        if chosen<0 { string terminal <- sum(ranr_base(travel))<=0.0 ? "failed" : "deferred"; ask ev { do cancel_request(terminal); } do ranr_finalize(ev,terminal,at); }
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
            ranr_recommendation_buffer <- ranr_recommendation_buffer+ev.request_id+","+at+","+issuer+","+recommended+","+chosen+",\""+to_json(result["weights"])+"\",\""+to_json(probability)+"\",\""+replace(to_json(result["estimates"]),'"','""')+"\","+entropy+"\n";
        }
        if ranr_calibrating and at>=ranr_warmup {
            map<string,unknown> context <- ["request_id"::ev.request_id,"vehicle_id"::ev.mobility_id,"kind"::ev.ranr_vehicle_kind,"chosen"::chosen,"issuer"::issuer,"travel"::travel,"energy"::request["energy"],"max_kw"::request["max_kw"],"participating"::participate];
            ranr_context_buffer <- ranr_context_buffer+'"'+replace(to_json(context),'"','""')+'"\n';
        }
        if participate { do ranr_broadcast(station,at); }
    }
    action ranr_finalize(elecar ev,string status,float at) {
        if ev.request_id in ranr_outcomes.keys { return nil; }
        map<string,unknown> demand <- ranr_demands[ev.request_id];
        if demand=nil { return nil; }
        at <- min(at,ev.request_time+ranr_deadline);
        float energy <- float(demand["energy"]); float missing <- max(0.0,min(1.0,1.0-ev.delivered_energy/max(energy,1e-12)));
        bool completed <- status="completed" and missing<1e-8;
        float penalty <- ranr_deadline*((completed ? 0.0 : 1.0)+missing);
        float waiting <- ev.waiting_time;
        if ev.session_state="waiting" and ev.arrival_time>=0.0 { waiting <- max(waiting,at-ev.arrival_time); }
        ranr_outcomes[ev.request_id] <- ["request_id"::ev.request_id,"vehicle_id"::demand["vehicle_id"],"kind"::demand["kind"],"key"::demand["key"],"issued_min"::demand["at"],"finished_min"::at,
            "status"::(completed ? "completed" : status),"requested_kwh"::energy,"delivered_kwh"::ev.delivered_energy,
            "travel_min"::ev.ranr_travel_min,"waiting_min"::waiting,"penalty_min"::penalty,"w_star"::(waiting+penalty),"t_star"::(ev.ranr_travel_min+waiting+penalty),"measured"::demand["measured"]];
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
                rows <- rows+terminal_record["request_id"]+","+terminal_record["event"]+","+terminal_record["time_min"]+","+terminal_record["energy_kwh"]+","+terminal_record["waiting_min"]+","+terminal_record["travel_m"]+"\n";
            }
            save rows to: ranr_output+"/events.csv" format:"text" rewrite:false; ranr_event_cursor <- length(session_events);
        }
    }
    action ranr_finish {
        do ranr_flush;
        list<map<string,unknown>> measured <- list(ranr_outcomes.values) where bool(each["measured"]);

        list<float> waits <- measured collect float(each["waiting_min"]);
        list<float> penalized <- measured collect (float(each["w_star"])/ranr_deadline);
        int installed <- int(sum(ranr_stations collect each.installed_port_count));
        float objective <- empty(measured) ? 0.0 : 0.5*mean(measured collect (float(each["t_star"])/ranr_deadline))+0.3*ranr_quantile(penalized,0.95)+0.2*ranr_peak_queue/installed;
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
                prediction_errors << float(estimates[chosen]["mean"])-float(outcome["waiting_min"]);
            }
        }
        float requested <- sum(measured collect float(each["requested_kwh"]));
        float delivered <- sum(measured collect float(each["delivered_kwh"]));
        map<string,unknown> metrics <- ["backend"::"GAMA","run_id"::ranr_run_id,"method"::ranr_method,"objective"::objective,"demand_count"::length(measured),
            "all_demand_count"::length(ranr_demands),"all_outcome_count"::length(ranr_outcomes),"served_count"::length(measured where (each["status"]="completed")),
            "mean_travel_min"::(empty(measured) ? 0.0 : mean(measured collect float(each["travel_min"]))),"mean_wait_min"::(empty(waits) ? 0.0 : mean(waits)),"p95_wait_min"::(empty(waits) ? 0.0 : ranr_quantile(waits,0.95)),
            "mean_total_min"::(empty(measured) ? 0.0 : mean(measured collect (float(each["travel_min"])+float(each["waiting_min"])))),"peak_queue"::ranr_peak_queue,
            "requested_kwh"::sum(measured collect float(each["requested_kwh"])),"delivered_kwh"::sum(measured collect float(each["delivered_kwh"])),
            "utilization"::(ranr_busy_port_minutes/(installed*ranr_measure)),"messages"::ranr_message_count,"communication_bytes"::ranr_message_bytes,
            "mean_weight_H"::(ranr_weight_h_sum/max(1,ranr_measured_recommendations)),
            "mean_active_weight_mass"::(ranr_method="No-Prediction" ? 1.0-ranr_weight_h_sum/max(1,ranr_measured_recommendations) : 1.0),
            "mean_recommendation_entropy"::(ranr_entropy_sum/max(1,ranr_measured_recommendations)),"received_messages"::ranr_received_count,"future_calls"::ranr_future_calls,"scenario_generations"::ranr_scenario_generations,"queue_calls"::ranr_queue_calls,
            "init_ms"::ranr_init_ms,"gis_ms"::ranr_gis_ms,"movement_ms"::ranr_movement_ms,"route_ms"::ranr_route_ms,"route_cache_hits"::ranr_route_hits,
            "prediction_ms"::ranr_prediction_ms,"externality_ms"::ranr_externality_ms,"policy_ms"::ranr_policy_ms,"information_ms"::ranr_information_ms];
        metrics <- ranr_record(metrics);
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
        loop terminal_status over: ["completed","failed","stranded","deferred","unserved"] { metrics[terminal_status+"_count"] <- length(measured where (each["status"]=terminal_status)); }
        assert length(ranr_outcomes)=length(ranr_demands);
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
        float at <- time/60.0;
        float interval <- max(0.0,min(at,ranr_warmup+ranr_measure)-max(ranr_last_tick,ranr_warmup));
        // Busy-port time is integrated from actual service duration, including boundary clipping.
        ranr_last_tick <- at;
        ask ranr_stations { do ranr_advance_service(at); }
        loop terminal_record over: ranr_terminal_events {
            string rid <- string(terminal_record["request_id"]);
            if !(rid in ranr_outcomes.keys) and rid in ranr_demands.keys {
                map<string,unknown> demand <- ranr_demands[rid]; float energy <- float(demand["energy"]);
                float missing <- max(0.0,min(1.0,1.0-float(terminal_record["energy"])/max(energy,1e-12)));
                bool completed <- terminal_record["status"]="completed" and missing<1e-8;
                float penalty <- ranr_deadline*((completed ? 0.0 : 1.0)+missing);
                ranr_outcomes[rid] <- ["request_id"::rid,"vehicle_id"::demand["vehicle_id"],"kind"::demand["kind"],"key"::demand["key"],"issued_min"::demand["at"],"finished_min"::terminal_record["at"],
                    "status"::terminal_record["status"],"requested_kwh"::energy,"delivered_kwh"::terminal_record["energy"],"travel_min"::terminal_record["travel"],"waiting_min"::terminal_record["waiting"],
                    "penalty_min"::penalty,"w_star"::(float(terminal_record["waiting"])+penalty),"t_star"::(float(terminal_record["travel"])+float(terminal_record["waiting"])+penalty),"measured"::demand["measured"]];
            }
        }
        ranr_terminal_events <- [];
        loop ev over: copy(ev_population) {
            if !(ev.request_id in ranr_demands.keys) { continue; }
            if ev.request_id in ranr_outcomes.keys { continue; }
            if ev.session_state="completed" { do ranr_finalize(ev,"completed",ev.service_finish); }
            else if ev.session_state="stranded" { do ranr_finalize(ev,"stranded",at); }
            else if at>=ev.request_time+ranr_deadline {
                if ev.session_state="waiting" { ev.waiting_time <- max(0.0,ev.request_time+ranr_deadline-ev.arrival_time); }
                ask ev { do cancel_request("unserved"); } do ranr_finalize(ev,"unserved",at);
            }
        }
        ask ranr_stations { do process_queue; }
        ask (ev_population where (each.session_state="en_route" and each.station_arrival_due>=0.0 and each.station_arrival_due<=at+1e-10)) sort_by each.ranr_demand_key { do start_charging; }
        do ranr_deliver(at);
        do ranr_fleet_tick(at);
        loop ev over: ev_population where (each.session_state="requested") sort_by each.ranr_demand_key { do ranr_process_request(ev); }
        loop station over: ranr_stations {
            if at>=station.ranr_next_broadcast {
                ask station { do ranr_capture(at); }
                do ranr_broadcast(station,at); station.ranr_next_broadcast <- at+ranr_broadcast_period;
                if ranr_calibrating and at>=ranr_warmup and at<ranr_warmup+ranr_measure {
                    loop fraction over: station.ranr_release_observed_fractions { ranr_fraction_buffer <- ranr_fraction_buffer+fraction+",-1\n"; }
                    loop fraction over: station.ranr_energy_observed_fractions { ranr_fraction_buffer <- ranr_fraction_buffer+"-1,"+fraction+"\n"; }
                    station.ranr_release_observed_fractions <- []; station.ranr_energy_observed_fractions <- [];
                    ranr_snapshot_buffer <- ranr_snapshot_buffer+'"'+replace(to_json(station.ranr_local_snapshot),'"','""')+'"\n';
                }
            }
        }
        if at>=ranr_warmup { ranr_peak_queue <- max(ranr_peak_queue,max(ranr_stations collect length(each.waiting_queue))); }
        if at>=ranr_next_flush { do ranr_flush; ranr_next_flush <- at+5.0; }
        if at>=ranr_warmup+ranr_measure+ranr_deadline { do ranr_finish; }
    }
}
