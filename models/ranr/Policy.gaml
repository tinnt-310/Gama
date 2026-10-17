model ranr_station_policy
import "Prediction.gaml"

species ranr_station_agent {
    int ranr_sid <- -1;
    map<string,unknown> ranr_local_snapshot <- [];
    map<int,map<string,unknown>> ranr_received <- [];
    map<int,int> ranr_received_sequence <- [];
    map<string,map<string,unknown>> ranr_local_exposure <- [];
    map<int,map<string,unknown>> ranr_request_cache <- [];
    map<string,map<string,unknown>> ranr_resolutions <- [];
    map<string,map<string,unknown>> ranr_forecast_history <- [];
    bool ranr_dirty <- false;
    bool ranr_critical <- false;
    float ranr_last_send <- -1e100;
    float ranr_last_workload <- 0.0;
    int ranr_last_exposure <- 0;
    int ranr_last_resolution <- 0;
    float ranr_last_capacity <- -1.0;
    int ranr_duplicate_packets <- 0;
    list<float> ranr_received_ages <- [];
    int ranr_sequence <- 0;
    float ranr_next_broadcast <- 0.0;
    list<float> ranr_local_requests <- [];
    float ranr_local_rate <- 0.0;

    action ranr_receive(map<string,unknown> packet,float at) {
        assert ranr_method!="No-P2P";
        assert float(packet["issued"])<=at+1e-10;
        int source <- int(packet["sender"]); int version <- int(packet["sequence"]);
        if source in ranr_received_sequence.keys and version<=ranr_received_sequence[source] { ranr_duplicate_packets <- ranr_duplicate_packets+1; return nil; }
        if "expires" in packet.keys and float(packet["expires"])<at { return nil; }
        if source in ranr_received.keys and float(packet["issued"])<float(ranr_received[source]["issued"]) { ranr_duplicate_packets <- ranr_duplicate_packets+1; return nil; }
        ranr_received[source] <- world.ranr_clone_packet(packet); ranr_received_sequence[source] <- version;
        ranr_received_ages << at-float(packet["issued"]);
        if "critical" in packet.keys and bool(packet["critical"]) { ranr_forecast_history <- []; }
    }
    map<string,unknown> ranr_observe(float at,list<map<string,unknown>> public_prior) {
        ranr_local_requests <- ranr_local_requests where (each>at-5.0);
        ranr_local_rate <- 0.5*ranr_prior_rate+0.5*length(ranr_local_requests)/5.0;
        list<map<string,unknown>> snapshots <- []; list<float> watermarks <- []; list<float> rates <- [];
        list<map<string,unknown>> exposure <- []; map<string,map<string,unknown>> resolutions <- copy(ranr_resolutions);
        loop sid from: 0 to: length(public_prior)-1 {
            map<string,unknown> snapshot <- world.ranr_clone_snapshot(public_prior[sid]); float watermark <- max(0.0,at-ranr_arrival_lookback); float rate <- ranr_prior_rate;
            if sid=ranr_sid {
                snapshot <- world.ranr_clone_snapshot(ranr_local_snapshot); watermark <- at; rate <- ranr_local_rate;
                exposure <- exposure+list(ranr_local_exposure.values);
            } else if ranr_method!="No-P2P" and sid in ranr_received.keys {
                map<string,unknown> packet <- ranr_received[sid];
                watermark <- max(0.0,float(packet["issued"]));
                if at-float(packet["issued"])<=ranr_ttl {
                    snapshot <- world.ranr_clone_snapshot(packet["snapshot"]); snapshot["source"] <- "peer";
                    watermark <- float(packet["issued"]); rate <- float(packet["rate"]);
                    exposure <- exposure+list<map<string,unknown>>(packet["exposure"]);
                    if "resolutions" in packet.keys { loop resolution over:list<map<string,unknown>>(packet["resolutions"]) { string token <- string(resolution["token"]); if !(token in resolutions.keys) or float(resolution["at"])>float(resolutions[token]["at"]) or (float(resolution["at"])=float(resolutions[token]["at"]) and int(resolution["version"])>int(resolutions[token]["version"])) { resolutions[token] <- resolution; } } }
                }
            }
            snapshots << snapshot; watermarks << watermark; rates << rate;
        }
        exposure <- exposure where (float(each["expires"])>=at);
        map<string,map<string,unknown>> unique <- [];
        loop cohort over:exposure {
            string token <- "token" in cohort.keys ? string(cohort["token"]) : string(cohort["key"]);
            if token in resolutions.keys { continue; }
            if !(token in unique.keys) or int(cohort["version"])>int(unique[token]["version"]) {
                map<string,unknown> remembered <- world.ranr_record(cohort);
                remembered["travel"] <- copy(cohort["travel"]);
                if "energy_by_station" in cohort.keys { remembered["energy_by_station"] <- copy(cohort["energy_by_station"]); }
                unique[token] <- remembered;
            }
        }
        exposure <- list(unique.values);
        loop cohort over:exposure { cohort["remaining_probability"] <- sum(world.ranr_outstanding_mass(cohort,at)); }
        return ["at"::at,"snapshots"::snapshots,"watermarks"::watermarks,"rates"::rates,"exposure"::exposure,"resolutions"::list(resolutions.values),"schema"::ranr_observation_version];
    }
    map<string,unknown> ranr_recommend(map<string,unknown> request,map<string,unknown> observation) {
        int key <- int(request["key"]);
        if (ranr_request_cache contains_key key) { return copy(ranr_request_cache[key]); }
        if "issuer" in request.keys { assert int(request["issuer"])=ranr_sid; }
        float started <- machine_time;
        ranr_local_requests <- (ranr_local_requests where (each>float(observation["at"])-5.0))+[float(observation["at"])];
        list<float> travel <- copy(list<float>(request["travel"]));
        list<map<string,unknown>> snapshots <- list(observation["snapshots"]);
        travel <- world.ranr_feasible_travel(request,observation);
        request <- world.ranr_record(request); request["travel"] <- travel;
        list<float> loads <- []; list<float> ages <- []; float ports <- 0.0;
        loop snapshot over: snapshots {
            list<float> power <- list<float>(snapshot["powers"]); ports <- ports+length(power);
            float load <- world.ranr_snapshot_load(snapshot);
            int sid <- int(snapshot["sid"]);
            if string(snapshot["source"])="prior" and sid in ranr_priors_by_sid.keys {
                list<map<string,unknown>> pool <- ranr_priors_by_sid[sid];
                load <- ranr_prior_load_by_sid[sid];
            }
            loads << load;
            ages << (string(snapshot["source"])="prior" ? ranr_ttl : max(0.0,float(observation["at"])-float(snapshot["issued"])));
        }
        float variance <- 0.0;
        loop cohort over: list<map<string,unknown>>(observation["exposure"]) {
            list<float> mass <- world.ranr_outstanding_mass(cohort,float(observation["at"]));
            float workload <- 60.0*float(cohort["energy"])/(charge_efficiency*120.0);
            variance <- variance+int(cohort["count"])*workload^2*max(0.0,sum(mass)-sum(mass collect (each^2)));
        }
        list<float> state <- [1.0,min(1.0,mean(loads)),min(1.0,length(ranr_local_requests)/10.0),min(1.0,sqrt(variance)/(60.0*sqrt(max(1.0,ports)))),min(1.0,mean(ages)/15.0)];
        list<float> weights <- world.ranr_weights(state); list<map<string,unknown>> estimates <- []; list<float> costs <- []; list<list<float>> raw_features <- []; list<list<float>> normalized_features <- [];
        loop sid from: 0 to: length(snapshots)-1 {
            if travel[sid]<0.0 {
                estimates << ["mean"::0.0,"p95"::0.0,"externality"::0.0,"uncertainty"::0.0,"source"::"infeasible"]; costs << 0.0; raw_features << [0.0,0.0,0.0,0.0,0.0]; normalized_features << [0.0,0.0,0.0,0.0,0.0]; continue;
            }
            map<string,unknown> estimate <- world.ranr_estimate(snapshots[sid],observation,request); estimates << estimate;
            string history_key <- string(sid)+":"+string(int(floor(travel[sid]/5.0)))+":"+string(request["max_kw"])+":"+string(int(floor(float(request["energy"])/5.0)));
            if ranr_stabilization!="off" and ranr_method!="No-Prediction" and !ranr_critical {
                if history_key in ranr_forecast_history.keys {
                    map<string,unknown> previous <- ranr_forecast_history[history_key];
                    if float(observation["at"])-float(previous["at"])<=ranr_broadcast_period and float(estimate["mean"])<=float(previous["raw_mean"])+ranr_event_workload {
                        loop statistic over:["mean","p95"] {
                            float stable <- (1.0-ranr_smoothing_alpha)*float(previous[statistic])+ranr_smoothing_alpha*float(estimate[statistic]);
                            if ranr_stabilization="smoothing_hysteresis" and abs(stable-float(previous[statistic]))<ranr_hysteresis_minutes { stable <- float(previous[statistic]); }
                            estimate[statistic] <- stable;
                        }
                    }
                }
            }
            ranr_forecast_history[history_key] <- ["at"::observation["at"],"raw_mean"::estimate["raw_mean"],"mean"::estimate["mean"],"p95"::estimate["p95"]];
            list<float> features <- [travel[sid]+float(estimate["charge"]),float(estimate["mean"]),float(estimate["p95"]),float(estimate["externality"]),float(estimate["uncertainty"])];
            raw_features << copy(features); list<float> normalized <- [];
            float cost <- 0.0;
            loop j from: 0 to: 4 { float value <- min(5.0,max(j=3 ? -5.0 : 0.0,features[j]/ranr_scales[j])); normalized << value; cost <- cost+weights[j]*value; }
            normalized_features << normalized; costs << cost;
        }
        list<float> base <- world.ranr_base(travel);
        if sum(base)<=0.0 {
            map<string,unknown> unavailable <- world.ranr_record(["selected"::-1,"probabilities"::base,"weights"::weights,"estimates"::estimates,"state"::state,"feasible_travel"::travel]);
            ranr_request_cache[key] <- unavailable; return unavailable;
        }
        list<float> logits <- []; list<int> feasible <- [];
        float alternative <- 0.0;
        // Explicit indexed dot product avoids duplicate-probability index ambiguity.
        alternative <- 0.0; loop sid from: 0 to: length(base)-1 { alternative <- alternative+base[sid]*costs[sid]; }
        loop sid from: 0 to: length(base)-1 {
            if travel[sid]<0.0 { continue; }
            list<float> response <- world.ranr_response_mass(travel,sid,"context" in request.keys ? string(request["context"]) : "default");
            float expected <- 0.0; loop j from:0 to:length(travel)-1 { expected <- expected+response[j]*costs[j]; }
            expected <- expected+response[length(travel)]*2.0*ranr_deadline/ranr_scales[1];
            float prior <- sum(list<float>(snapshots[sid]["powers"]))/ (1.0+travel[sid]/30.0);
            logits << ln(prior)-expected/ranr_temperature; feasible << sid;
        }
        list<float> mass <- world.ranr_softmax(logits); list<float> probabilities <- world.zero_vector(length(base));
        loop j from: 0 to: length(feasible)-1 { probabilities[feasible[j]] <- mass[j]; }
        int selected <- feasible[world.ranr_categorical(mass,world.ranr_uniform(201,key,0))];
        map<string,unknown> result <- ["selected"::selected,"probabilities"::probabilities,"weights"::weights,"estimates"::estimates,"state"::state,"feasible_travel"::travel];
        ranr_request_cache[key] <- result;
        ranr_local_rate <- 0.5*ranr_prior_rate+0.5*length(ranr_local_requests)/5.0;
        string token <- "token" in request.keys ? string(request["token"]) : string(ranr_sid)+":"+string(key)+":0";
        map<string,unknown> cohort <- world.ranr_record(["key"::key,"token"::token,"anonymous"::false,"sender"::ranr_sid,"recommended"::selected,"count"::1,"version"::1,
            "context"::("context" in request.keys ? request["context"] : "default"),"issued"::observation["at"],"expires"::(float(observation["at"])+("remaining_observation" in request.keys ? float(request["remaining_observation"]) : ranr_warmup+ranr_measure+ranr_deadline)),
            "eta_profile"::ranr_calibration_source,"bucket"::int(floor(float(observation["at"])/5.0)),"travel"::copy(travel),"energy"::request["energy"],"max_kw"::request["max_kw"],"resolved"::false]);
        if "energy_by_station" in request.keys { cohort["energy_by_station"] <- copy(request["energy_by_station"]); }
        ranr_local_exposure[token] <- cohort; ranr_dirty <- true;
        if length(ranr_local_exposure)-ranr_last_exposure>=ranr_event_exposure { ranr_forecast_history <- []; ranr_critical <- true; }
        ranr_policy_ms <- ranr_policy_ms+machine_time-started;
        float latency <- machine_time-started; ranr_policy_latencies << latency;
        result["costs"] <- costs; result["raw_features"] <- raw_features; result["normalized_features"] <- normalized_features; result["state"] <- state;
        return result;
    }
    action ranr_resolve(string token,string status,float at) {
        if token="" { return nil; }
        if token in ranr_resolutions.keys and string(ranr_resolutions[token]["status"])=status { return nil; }
        map<string,unknown> resolution <- world.ranr_record(["token"::token,"status"::status,"version"::(status="arrived" ? 1 : 2),"at"::at,"source"::ranr_sid,"expires"::max(at+ranr_ttl,ranr_warmup+ranr_measure+ranr_deadline)]);
        if token in ranr_resolutions.keys {
            map<string,unknown> previous <- ranr_resolutions[token];
            if previous["status"]="arrived" or "arrival_at" in previous.keys {
                resolution["arrival_at"] <- "arrival_at" in previous.keys ? previous["arrival_at"] : previous["at"];
                loop field_name over:["energy","max_kw","service_until"] { if field_name in previous.keys { resolution[field_name] <- previous[field_name]; } }
            }
        }
        ranr_resolutions[token] <- resolution;
        if token in ranr_local_exposure.keys { remove key:token from:ranr_local_exposure; }
        ranr_dirty <- true; ranr_forecast_history <- [];
    }
}
