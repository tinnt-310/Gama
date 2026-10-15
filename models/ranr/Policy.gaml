model ranr_station_policy
import "Prediction.gaml"

species ranr_station_agent {
    int ranr_sid <- -1;
    map<string,unknown> ranr_local_snapshot <- [];
    map<int,map<string,unknown>> ranr_received <- [];
    map<int,int> ranr_received_sequence <- [];
    map<string,map<string,unknown>> ranr_local_exposure <- [];
    map<int,map<string,unknown>> ranr_request_cache <- [];
    int ranr_sequence <- 0;
    float ranr_next_broadcast <- 0.0;
    list<float> ranr_local_requests <- [];
    float ranr_local_rate <- 0.0;

    action ranr_receive(map<string,unknown> packet,float at) {
        assert ranr_method!="No-P2P";
        assert float(packet["issued"])<=at+1e-10;
        int source <- int(packet["sender"]); int version <- int(packet["sequence"]);
        if source in ranr_received_sequence.keys and version<=ranr_received_sequence[source] { return nil; }
        ranr_received[source] <- world.ranr_clone_packet(packet); ranr_received_sequence[source] <- version;
    }
    map<string,unknown> ranr_observe(float at,list<map<string,unknown>> public_prior) {
        ranr_local_requests <- ranr_local_requests where (each>at-5.0);
        ranr_local_rate <- 0.5*ranr_prior_rate+0.5*length(ranr_local_requests)/5.0;
        list<map<string,unknown>> snapshots <- []; list<float> watermarks <- []; list<float> rates <- [];
        list<map<string,unknown>> exposure <- [];
        loop sid from: 0 to: length(public_prior)-1 {
            map<string,unknown> snapshot <- world.ranr_clone_snapshot(public_prior[sid]); float watermark <- max(0.0,at-ranr_ttl); float rate <- ranr_prior_rate;
            if sid=ranr_sid {
                snapshot <- world.ranr_clone_snapshot(ranr_local_snapshot); watermark <- at; rate <- ranr_local_rate;
                exposure <- exposure+list(ranr_local_exposure.values);
            } else if ranr_method!="No-P2P" and sid in ranr_received.keys {
                map<string,unknown> packet <- ranr_received[sid];
                if at-float(packet["issued"])<=ranr_ttl {
                    snapshot <- world.ranr_clone_snapshot(packet["snapshot"]); snapshot["source"] <- "peer";
                    watermark <- float(packet["issued"]); rate <- float(packet["rate"]);
                    exposure <- exposure+list(packet["exposure"]);
                }
            }
            snapshots << snapshot; watermarks << watermark; rates << rate;
        }
        exposure <- exposure where (float(each["expires"])>=at);
        return ["at"::at,"snapshots"::snapshots,"watermarks"::watermarks,"rates"::rates,"exposure"::exposure];
    }
    map<string,unknown> ranr_recommend(map<string,unknown> request,map<string,unknown> observation) {
        int key <- int(request["key"]);
        if key in ranr_request_cache.keys { return copy(ranr_request_cache[key]); }
        float started <- machine_time;
        list<float> travel <- list<float>(request["travel"]);
        list<map<string,unknown>> snapshots <- list(observation["snapshots"]);
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
        loop cohort over: list(observation["exposure"]) {
            list<float> mass <- world.ranr_outstanding_mass(cohort,float(observation["at"]));
            float workload <- 60.0*float(cohort["energy"])/(charge_efficiency*120.0);
            variance <- variance+int(cohort["count"])*workload^2*max(0.0,sum(mass)-sum(mass collect (each^2)));
        }
        list<float> state <- [1.0,min(1.0,mean(loads)),min(1.0,length(ranr_local_requests)/10.0),min(1.0,sqrt(variance)/(60.0*sqrt(max(1.0,ports)))),min(1.0,mean(ages)/15.0)];
        list<float> weights <- world.ranr_weights(state); list<map<string,unknown>> estimates <- []; list<float> costs <- [];
        loop sid from: 0 to: length(snapshots)-1 {
            if travel[sid]<0.0 {
                estimates << ["mean"::0.0,"p95"::0.0,"externality"::0.0,"uncertainty"::0.0,"source"::"infeasible"]; costs << 0.0; continue;
            }
            map<string,unknown> estimate <- world.ranr_estimate(snapshots[sid],observation,request); estimates << estimate;
            list<float> features <- [travel[sid],float(estimate["mean"]),float(estimate["p95"]),float(estimate["externality"]),float(estimate["uncertainty"])];
            float cost <- 0.0;
            loop j from: 0 to: 4 { cost <- cost+weights[j]*min(5.0,max(j=3 ? -5.0 : 0.0,features[j]/ranr_scales[j])); }
            costs << cost;
        }
        list<float> base <- world.ranr_base(travel);
        if sum(base)<=0.0 { return ["selected"::-1,"probabilities"::base,"weights"::weights,"estimates"::estimates,"state"::state]; }
        list<float> logits <- []; list<int> feasible <- [];
        float alternative <- 0.0;
        // Explicit indexed dot product avoids duplicate-probability index ambiguity.
        alternative <- 0.0; loop sid from: 0 to: length(base)-1 { alternative <- alternative+base[sid]*costs[sid]; }
        loop sid from: 0 to: length(base)-1 {
            if travel[sid]<0.0 { continue; }
            float expected <- (1.0-ranr_assumed_defer)*(ranr_assumed_compliance*costs[sid]+(1.0-ranr_assumed_compliance)*alternative)+ranr_assumed_defer*2.0*ranr_deadline/ranr_scales[1];
            float prior <- sum(list<float>(snapshots[sid]["powers"]))/ (1.0+travel[sid]/30.0);
            logits << ln(prior)-expected/ranr_temperature; feasible << sid;
        }
        list<float> mass <- world.ranr_softmax(logits); list<float> probabilities <- world.zero_vector(length(base));
        loop j from: 0 to: length(feasible)-1 { probabilities[feasible[j]] <- mass[j]; }
        int selected <- feasible[world.ranr_categorical(mass,world.ranr_uniform(201,key,0))];
        map<string,unknown> result <- ["selected"::selected,"probabilities"::probabilities,"weights"::weights,"estimates"::estimates,"state"::state];
        ranr_request_cache[key] <- result;
        ranr_local_requests <- (ranr_local_requests where (each>float(observation["at"])-5.0))+[float(observation["at"])];
        ranr_local_rate <- 0.5*ranr_prior_rate+0.5*length(ranr_local_requests)/5.0;
        int bucket <- int(floor(float(observation["at"])/5.0));
        int cohort_key <- bucket*1000000+ranr_sid*10000+selected*500+int(floor(float(request["energy"])/5.0))*10+int(float(request["max_kw"])/50.0);
        int feasibility_mask <- 0;
        loop sid from: 0 to: length(travel)-1 { if travel[sid]>=0.0 { feasibility_mask <- feasibility_mask+int(2^sid); } }
        string cohort_index <- string(cohort_key)+"_"+string(feasibility_mask);
        int random_key <- int(world.keyed_uniform(seed,705,cohort_key,feasibility_mask)*2147483646.0);
        // Start with a heterogeneous record; a literal initializer can make
        // GAML infer list-valued contents and cast later scalar updates to lists.
        map<string,unknown> cohort <- world.ranr_record(["key"::random_key,"sender"::ranr_sid,"recommended"::selected,"count"::1,"version"::1,
            "issued"::observation["at"],"expires"::(float(observation["at"])+ranr_ttl),"travel"::copy(travel),"energy"::request["energy"],"max_kw"::request["max_kw"]]);
        if cohort_index in ranr_local_exposure.keys {
            map<string,unknown> previous <- ranr_local_exposure[cohort_index]; int count <- int(previous["count"]);
            cohort["count"] <- count+1; cohort["version"] <- int(previous["version"])+1;
            cohort["issued"] <- (count*float(previous["issued"])+float(observation["at"]))/ (count+1);
            list<float> average <- []; loop j from: 0 to: length(travel)-1 { average << (count*list<float>(previous["travel"])[j]+travel[j])/(count+1); }
            cohort["travel"] <- average; cohort["energy"] <- (count*float(previous["energy"])+float(request["energy"]))/ (count+1);
        }
        ranr_local_exposure[cohort_index] <- cohort;
        ranr_policy_ms <- ranr_policy_ms+machine_time-started;
        return result;
    }
}
