model recommendation_runtime
import "Coordination.gaml"

global {
    string recommendation_method <- "minimax";
    string normalization_mode <- "feasible";
    list<float> recommendation_weights <- []; // Required explicitly for weighted comparators.
    string ev_choice_mode <- "FOLLOW_RECOMMENDATION";
    string exogenous_choice_trace_file <- "";
    map<string,list<map>> external_choice_records <- [];
    bool publish_intention <- false; // Explicit optional report, never a reservation or forecast input.
    bool recommendation_initialized <- false;
    float next_recommendation_epoch <- 0.0;
    list<map> recommendation_records <- [];
    list<map> recommendation_candidate_records <- [];
    int exported_recommendation_count <- 0;
    int exported_candidate_count <- 0;
    list<map> unavailable_recommendations <- [];
    int exported_unavailable_count <- 0;
    int query_messages <- 0;
    int response_messages <- 0;
    int query_bytes <- 0;
    int response_bytes <- 0;
    float recommendation_runtime_ms <- 0.0;
    int recommendation_record_cursor <- 0;

    action initialize_recommendation {
        assert runtime_mode = "RECOMMENDATION_RUNTIME";
        assert service_backend = "fixed_port" and oracle_backend = "fixed_port";
        assert waiting_forecast_mode in ["B3","B4","B4-N"];
        assert information_mode in ["LIVE_STATION_INFORMATION","LIMITED_INFORMATION"];
        assert ev_choice_mode in ["FOLLOW_RECOMMENDATION","SELF_INTERESTED_CHOICE","EXOGENOUS_CHOICE_TRACE","DEFER_CHOICE"];
        assert step > 0.0 and observation_bin_minutes > 0.0 and observation_window > 0;
        assert replay_scenarios > 0 and forecast_horizon_bins > 0 and ridge_penalty > 0.0 and forecast_feature_scale > 0.0;
        assert normalization_mode in ["feasible","pareto"];
        if recommendation_method in ["weighted_sum","monetary"] {
            assert length(recommendation_weights) = 4 and min(recommendation_weights) >= 0.0 and sum(recommendation_weights) > 0.0;
        }
        if exogenous_choice_trace_file != "" {
            assert file_exists(exogenous_choice_trace_file);
            matrix trace_data <- matrix(csv_file(exogenous_choice_trace_file,",",string));
            assert trace_data.columns = 3;
            assert string(trace_data[0,0]) = "request_id" and string(trace_data[1,0]) = "time_min" and string(trace_data[2,0]) = "station";
            if trace_data.rows > 1 {
                loop row_index from: 1 to: trace_data.rows-1 {
                    string rid <- string(trace_data[0,row_index]);
                    if !(rid in external_choice_records.keys) { external_choice_records[rid] <- []; }
                    list<map> records <- external_choice_records[rid];
                    records << ["time"::float(trace_data[1,row_index]),"station"::string(trace_data[2,row_index])];
                    external_choice_records[rid] <- records;
                }
            }
        }
        assert waiting_estimator_mode in ["replay","fluid"] and ood_fallback_mode in ["physical_only","fluid"];
        do prepare_run_output;
        // Topology setup uses only public graph/station access metadata, not physical demand.
        loop station over: charging_station {
            list<map> choices <- [];
            if road_network != nil and station.closest_intersection != nil {
                loop other over: charging_station where (each != station and each.closest_intersection != nil) {
                    path route <- path_between(road_network,station.closest_intersection,other.closest_intersection);
                    if route = nil { continue; }
                    float route_minutes <- sum(route.edges collect (road(each).shape.perimeter/max(1e-6,ele_car_speed/3.6)/60.0));
                    choices << ["station"::other,"travel"::route_minutes,"sid"::other.index];
                }
            }
            choices <- (choices sort_by int(each["sid"])) sort_by float(each["travel"]);
            station.information_neighbors <- [];
            if !empty(choices) and communication_degree > 0 {
                loop k from: 0 to: min(communication_degree,length(choices))-1 { station.information_neighbors << charging_station(choices[k]["station"]); }
            }
        }
        loop station over: charging_station {
            loop other over: copy(station.information_neighbors) {
                if !(station in other.information_neighbors) { other.information_neighbors << station; }
            }
        }
        string neighbor_graph_csv <- "sender,receiver\n";
        loop station over: charging_station { loop other over: station.information_neighbors { neighbor_graph_csv <- neighbor_graph_csv+station.name+","+other.name+"\n"; } }
        save neighbor_graph_csv to: run_prefix+"_neighbor_graph.csv" format: "text";
        string config <- "schema_version,runtime,forecast,information,choice,score,normalization,bin_min,history_window,min_bins,min_sessions,replay_count,replay_threshold,ridge_penalty,neighbor_degree,delay_min,neighbor_correction_enabled,synthetic,behavior_calibrated,hard_inbound,clock_step_seconds,seed,candidate_mode,charging_goal,target_soc,battery_kwh,consumption_kwh_km,efficiency,reference_power_kw,reference_efficiency,waiting_estimator,ood_fallback,weight_T,weight_D,weight_E,weight_W\n";
        config <- config+"2,"+runtime_mode+","+waiting_forecast_mode+","+information_mode+","+ev_choice_mode+","+recommendation_method+","+normalization_mode+","+observation_bin_minutes+","+observation_window+","+observation_min_bins+","+observation_min_sessions+","+replay_scenarios+","+replay_similarity_threshold+","+ridge_penalty+","+communication_degree+","+neighbor_delay_minutes+","+neighbor_correction_enabled+",true,false,false,"+step+","+seed+","+candidate_mode+","+charging_goal+","+target_soc+","+battery_capacity_kwh+","+consumption_kwh_km+","+charge_efficiency+","+reference_power_kw+","+reference_efficiency+","+waiting_estimator_mode+","+ood_fallback_mode+","+(length(recommendation_weights)=4 ? recommendation_weights[0] : -1.0)+","+(length(recommendation_weights)=4 ? recommendation_weights[1] : -1.0)+","+(length(recommendation_weights)=4 ? recommendation_weights[2] : -1.0)+","+(length(recommendation_weights)=4 ? recommendation_weights[3] : -1.0)+"\n";
        save config to: run_prefix+"_recommendation_config.csv" format: "text";
        recommendation_initialized <- true;
    }
    action update_station_forecasts {
        float at <- time/60.0;
        // Barrier: deliver already available messages before any station issues a new forecast.
        ask charging_station { do receive_available_forecasts(at); }
        ask charging_station where (at+1e-10 >= each.next_forecast_min) {
            do issue_station_forecast(at);
            next_forecast_min <- at+observation_bin_minutes;
        }
    }
    action generate_recommendation(elecar ev) {
        // Snapshot only: this action does not modify destination or inbound.
        do build_candidates(ev);
        ev.received_station_options <- [];
        ev.recommendation_result <- []; ev.recommended_station <- nil;
        if empty(ev.candidates) {
            ev.recommendation_result <- ["status"::"unavailable","reason"::"no_feasible_candidate"];
            unavailable_recommendations << ["request_id"::ev.request_id,"issued_at"::epoch_min,"reason"::"no_feasible_candidate"];
            return nil;
        }
        loop k from: 0 to: length(ev.candidates)-1 {
            charging_station station <- ev.candidates[k];
            float offset <- ev.candidate_eta[k]-epoch_min;
            map<string,unknown> prediction <- [];
            query_messages <- query_messages+1;
            query_bytes <- query_bytes+length(ev.request_id)+length(string(ev.candidate_eta[k]))+length(string(ev.candidate_requested_energy[k]));
            if information_mode = "LIVE_STATION_INFORMATION" {
                prediction <- station.predict_waiting(epoch_min,offset);
            } else {
                map packet <- station.advertised_waiting;
                if empty(packet) { continue; }
                list<float> curve <- list<float>(packet["waiting"]);
                float age <- epoch_min-float(packet["issued_at"]);
                int slot <- int(ceil(age+offset-1e-10));
                if slot < 0 or slot >= length(curve) or curve[slot] < 0.0 { continue; }
                list<string> statuses <- list<string>(packet["statuses"]);
                prediction <- ["waiting"::(curve[slot]+slot-age-offset),"status"::("stale_"+statuses[slot]),"issued_at"::packet["issued_at"],"error"::-1.0,"scenario_count"::0,"scenario_spread"::-1.0];
            }
            if float(prediction["waiting"]) < 0.0 { continue; }
            response_messages <- response_messages+1; response_bytes <- response_bytes+length(string(prediction));
            ev.received_station_options << ["station"::station,"sid"::station.index,"eta"::ev.candidate_eta[k],
                "criteria"::[offset,ev.candidate_distance[k]/1000.0,ev.candidate_energy[k],float(prediction["waiting"])],
                "energy_to_receive"::ev.candidate_requested_energy[k],"workload"::ev.candidate_workload[k],
                "snapshot"::prediction["issued_at"],"received_at"::epoch_min,"forecast_status"::prediction["status"],
                "replay_error"::prediction["error"],"scenario_count"::prediction["scenario_count"],"scenario_spread"::prediction["scenario_spread"]];
        }
        if empty(ev.received_station_options) {
            ev.recommendation_result <- ["status"::"unavailable","reason"::"no_valid_station_information"];
            unavailable_recommendations << ["request_id"::ev.request_id,"issued_at"::epoch_min,"reason"::"no_valid_station_information"];
            return nil;
        }
        list<map> ranked <- ev.rank_received_options(normalization_mode,recommendation_method,recommendation_weights);
        ev.received_station_options <- ranked;
        map selected <- first(ranked where bool(each["recommended"]));
        ev.recommendation_version <- ev.recommendation_version+1;
        ev.recommended_station <- charging_station(selected["station"]);
        ev.recommendation_result <- copy(selected);
        ev.recommendation_result["request_id"] <- ev.request_id;
        ev.recommendation_result["version"] <- ev.recommendation_version;
        ev.recommendation_result["issued_at"] <- epoch_min;
        ev.recommendation_result["choice"] <- "";
        ev.recommendation_result["feasible_count"] <- length(ev.candidates);
        ev.recommendation_result["available_count"] <- length(ranked);
        recommendation_records << copy(ev.recommendation_result);
        loop option over: ranked {
            map row <- copy(option); row["request_id"] <- ev.request_id; row["issued_at"] <- epoch_min;
            row["version"] <- ev.recommendation_version;
            recommendation_candidate_records << row;
        }
    }
    action execute_ev_choice(elecar ev) {
        if empty(ev.received_station_options) or !(ev.session_state in ["requested","deferred"]) { return nil; }
        if ev_choice_mode = "DEFER_CHOICE" { return nil; }
        map selected <- ev.recommendation_result;
        if ev_choice_mode = "SELF_INTERESTED_CHOICE" {
            list<map> personal <- ev.rank_received_options(normalization_mode,ev.personal_choice_method,ev.personal_weights);
            selected <- first(personal where bool(each["recommended"]));
        }
        if ev_choice_mode = "EXOGENOUS_CHOICE_TRACE" {
            if exogenous_choice_trace_file != "" {
                if !(ev.request_id in external_choice_records.keys) { write "CHOICE_TRACE_MISSING " + ev.request_id; assert false; }
                ev.choice_trace <- external_choice_records[ev.request_id];
            }
            if empty(ev.choice_trace) { write "CHOICE_TRACE_MISSING " + ev.request_id; assert false; }
            list<map> available <- ev.choice_trace where (float(each["time"]) <= epoch_min);
            if empty(available) { return nil; }
            ev.trace_loaded_for_request <- ev.request_id;
            map entry <- last(available sort_by float(each["time"]));
            if string(entry["station"]) = "" { return nil; }
            list<map> options <- ev.received_station_options where (charging_station(each["station"]).name = string(entry["station"]));
            if empty(options) { write "CHOICE_TRACE_INFEASIBLE " + ev.request_id; return nil; }
            selected <- options[0];
        }
        charging_station destination_station <- charging_station(selected["station"]);
        // Optional reports are explicit; the station forecaster never consumes these records.
        if publish_intention {
            ask destination_station { do report_intention(ev.request_id,float(selected["eta"]),float(selected["workload"])); }
        }
        ev.chosen_forecast_status <- string(selected["forecast_status"]);
        ev.predicted_waiting_at_choice <- float(list(selected["criteria"])[3]);
        ask ev {
            do apply_station_choice(destination_station,float(selected["eta"]),float(list(selected["criteria"])[2]),float(selected["energy_to_receive"]),float(selected["workload"]));
        }
    }
    action recommendation_batch {
        if !recommendation_initialized { do initialize_recommendation; }
        float started_at <- machine_time;
        epoch_min <- time/60.0;
        do update_station_forecasts;
        list<elecar> pending <- ev_population where (each.session_state in ["requested","deferred"]);
        loop ev over: pending { do generate_recommendation(ev); }
        // All recommendations use the same pre-choice state; no sequential inbound feedback.
        loop ev over: pending { do execute_ev_choice(ev); }
        recommendation_runtime_ms <- recommendation_runtime_ms+float(machine_time)-started_at;
        do export_recommendations;
    }
    action export_forecast_diagnostics {
        string forecast_rows <- ""; string evaluation_rows <- ""; string comm_rows <- "";
        if !file_exists(run_prefix+"_forecasts.csv") {
            save "station,issued_at,horizon,local_workload,corrected_workload\n" to: run_prefix+"_forecasts.csv" format: "text";
            save "station,issued_at,observed_at,horizon,actual_workload,local_workload,corrected_workload\n" to: run_prefix+"_forecast_errors.csv" format: "text";
            save "sender,receiver,issued_at,received_at,latency_min,logical_bytes\n" to: run_prefix+"_communication.csv" format: "text";
        }
        loop station over: charging_station {
            if station.exported_forecasts < length(station.issued_forecasts) {
                loop i from: station.exported_forecasts to: length(station.issued_forecasts)-1 {
                    map packet <- station.issued_forecasts[i]; list<float> baseline <- list<float>(packet["local"]); list<float> corrected <- list<float>(packet["workload"]);
                    loop h from: 0 to: length(baseline)-1 { forecast_rows <- forecast_rows+station.name+","+packet["issued_at"]+","+h+","+baseline[h]+","+corrected[h]+"\n"; }
                }
                station.exported_forecasts <- length(station.issued_forecasts);
            }
            if station.exported_forecast_evaluations < length(station.forecast_evaluations) {
                loop i from: station.exported_forecast_evaluations to: length(station.forecast_evaluations)-1 {
                    map record <- station.forecast_evaluations[i];
                    evaluation_rows <- evaluation_rows+station.name+","+record["issued_at"]+","+record["observed_at"]+","+record["horizon"]+","+record["actual"]+","+record["local"]+","+record["corrected"]+"\n";
                }
                station.exported_forecast_evaluations <- length(station.forecast_evaluations);
            }
            if station.exported_communications < length(station.communication_events) {
                loop i from: station.exported_communications to: length(station.communication_events)-1 {
                    map record <- station.communication_events[i];
                    comm_rows <- comm_rows+record["sender"]+","+record["receiver"]+","+record["issued_at"]+","+record["received_at"]+","+record["latency"]+","+record["bytes"]+"\n";
                }
                station.exported_communications <- length(station.communication_events);
            }
        }
        if forecast_rows != "" { save forecast_rows to: run_prefix+"_forecasts.csv" format: "text" rewrite: false; }
        if evaluation_rows != "" { save evaluation_rows to: run_prefix+"_forecast_errors.csv" format: "text" rewrite: false; }
        if comm_rows != "" { save comm_rows to: run_prefix+"_communication.csv" format: "text" rewrite: false; }
    }
    action export_recommendations {
        do export_forecast_diagnostics;
        if !file_exists(run_prefix+"_recommendation_unavailable.csv") {
            save "request_id,issued_at,reason\n" to: run_prefix+"_recommendation_unavailable.csv" format: "text";
        }
        if exported_unavailable_count < length(unavailable_recommendations) {
            string unavailable_rows <- "";
            loop k from: exported_unavailable_count to: length(unavailable_recommendations)-1 {
                map item <- unavailable_recommendations[k];
                unavailable_rows <- unavailable_rows+item["request_id"]+","+item["issued_at"]+","+item["reason"]+"\n";
            }
            save unavailable_rows to: run_prefix+"_recommendation_unavailable.csv" format: "text" rewrite: false;
            exported_unavailable_count <- length(unavailable_recommendations);
        }
        if exported_recommendation_count = 0 {
            save "schema_version,request_id,version,issued_at,recommended_station,score,snapshot_time,forecast_status,replay_error,scenario_count,predicted_eta,travel_min,distance_km,energy_kwh,predicted_wait_min,feasible_candidates,available_candidates,score_method,monetary_cost_vnd,received_at,scenario_spread\n" to: run_prefix+"_recommendations.csv" format: "text";
        }
        if exported_candidate_count = 0 {
            save "request_id,version,issued_at,station,pareto,recommended,score,travel_min,distance_km,energy_kwh,predicted_wait_min,snapshot_time,forecast_status,score_method,alternative_rank,regret_T,regret_D,regret_E,regret_W,replay_error,scenario_count,scenario_spread,received_at\n" to: run_prefix+"_recommendation_candidates.csv" format: "text";
        }
        string rows <- "";
        if exported_recommendation_count < length(recommendation_records) {
            loop k from: exported_recommendation_count to: length(recommendation_records)-1 {
                map item <- recommendation_records[k]; list<float> values <- list<float>(item["criteria"]);
                rows <- rows+"2,"+item["request_id"]+","+item["version"]+","+item["issued_at"]+","+charging_station(item["station"]).name+","+item["score"]+","+item["snapshot"]+","+item["forecast_status"]+","+item["replay_error"]+","+item["scenario_count"]+","+item["eta"]+","+values[0]+","+values[1]+","+values[2]+","+values[3]+","+item["feasible_count"]+","+item["available_count"]+","+item["score_method"]+","+(string(item["score_method"]) = "monetary" ? string(item["score"]) : "")+","+item["received_at"]+","+item["scenario_spread"]+"\n";
            }
            save rows to: run_prefix+"_recommendations.csv" format: "text" rewrite: false;
            exported_recommendation_count <- length(recommendation_records);
        }
        rows <- "";
        if exported_candidate_count < length(recommendation_candidate_records) {
            loop k from: exported_candidate_count to: length(recommendation_candidate_records)-1 {
                map item <- recommendation_candidate_records[k]; list<float> values <- list<float>(item["criteria"]); list<float> regrets <- list<float>(item["regrets"]);
                rows <- rows+item["request_id"]+","+item["version"]+","+item["issued_at"]+","+charging_station(item["station"]).name+","+item["pareto"]+","+item["recommended"]+","+item["score"]+","+values[0]+","+values[1]+","+values[2]+","+values[3]+","+item["snapshot"]+","+item["forecast_status"]+","+item["score_method"]+","+item["alternative_rank"]+","+regrets[0]+","+regrets[1]+","+regrets[2]+","+regrets[3]+","+item["replay_error"]+","+item["scenario_count"]+","+item["scenario_spread"]+","+item["received_at"]+"\n";
            }
            save rows to: run_prefix+"_recommendation_candidates.csv" format: "text" rewrite: false;
            exported_candidate_count <- length(recommendation_candidate_records);
        }
        int messages <- sum(list(charging_station) collect each.station_message_count);
        int bytes <- sum(list(charging_station) collect each.station_message_bytes);
        string metrics <- "time_min,query_messages,response_messages,station_messages,query_bytes,response_bytes,station_bytes,runtime_ms,shadow_calls,cache_hits,logical_communication\n";
        metrics <- metrics+time/60.0+","+query_messages+","+response_messages+","+messages+","+query_bytes+","+response_bytes+","+bytes+","+recommendation_runtime_ms+","+sum(list(charging_station) collect each.shadow_calls)+","+sum(list(charging_station) collect each.waiting_cache_hits)+",true\n";
        save metrics to: run_prefix+"_recommendation_metrics.csv" format: "text";
    }
    reflex recommendation_epoch when: coordination_enabled and runtime_mode = "RECOMMENDATION_RUNTIME" and time >= next_recommendation_epoch {
        do recommendation_batch;
        next_recommendation_epoch <- time+batch_seconds;
    }
}
