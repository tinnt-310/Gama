model ranr_prediction
import "Math.gaml"

global {
    // Inputs contain public/copied numeric data only; never physical agent references.
    list<map<string,unknown>> ranr_generate_future(map<string,unknown> observation,map<string,unknown> request,int sample) {
        ranr_scenario_generations <- ranr_scenario_generations+1;
        float origin <- "origin" in observation.keys ? float(observation["origin"]) : float(observation["at"]);
        if "snapshots" in observation.keys { list<map<string,unknown>> snapshots <- observation["snapshots"]; loop snapshot over: snapshots { if snapshot["source"]!="prior" { origin <- min(origin,float(snapshot["issued"])); } } }
        float now <- float(observation["at"]); float end_at <- now+max(list<float>(request["travel"]))+ranr_horizon;
        int entity <- int(request["key"])*4099+sample;
        list<map<string,unknown>> arrivals <- [];
        loop cohort over: list<map<string,unknown>>(observation["exposure"]) {
            list<float> travel <- list<float>(cohort["travel"]);
            list<float> mass <- ranr_response_mass(travel,int(cohort["recommended"]),"context" in cohort.keys ? string(cohort["context"]) : "default");
            if int(cohort["count"]) > 0 {
                loop k from: 0 to: int(cohort["count"])-1 {
                    int draw <- int(cohort["key"])*131+k;
                    if ranr_uniform(327,entity,draw)>ranr_arrival_probability { continue; }
                    int chosen <- ranr_categorical(mass,ranr_uniform(301,entity,draw));
                    if chosen>=length(travel) { continue; }
                    float factor <- ranr_eta_factor(entity:entity,draw:draw);
                    if "snapshots" in observation.keys {
                        list<map<string,unknown>> states <- observation["snapshots"];
                        map<string,unknown> candidate <- states[chosen];
                        if "anonymous_count" in candidate.keys and (!("token" in cohort.keys) or ("anonymous" in cohort.keys and bool(cohort["anonymous"]))) {
                            float since <- float(candidate["anonymous_window"]); float until <- float(candidate["issued"]);
                            list<float> inside <- ranr_eta_factors where (float(cohort["issued"])+each*travel[chosen]>since and float(cohort["issued"])+each*travel[chosen]<=until);
                            list<float> outside <- ranr_eta_factors where (!(float(cohort["issued"])+each*travel[chosen]>since and float(cohort["issued"])+each*travel[chosen]<=until));
                            float probability <- float(length(inside))/length(ranr_eta_factors);
                            float prior_other <- max(0.0,ranr_prior_rate*(until-since));
                            float posterior <- ranr_seen_posterior(probability,int(candidate["anonymous_count"]),prior_other);
                            bool seen <- ranr_uniform(325,entity,draw)<posterior;
                            list<float> conditioned <- seen ? inside : outside;
                            if !empty(conditioned) { factor <- conditioned[min(length(conditioned)-1,int(ranr_uniform(326,entity,draw)*length(conditioned)))]; }
                        }
                    }
                    float absolute <- float(cohort["issued"])+factor*travel[chosen];
                    if absolute > origin+1e-10 and absolute <= end_at {
                        arrivals << ["sid"::chosen,"at"::absolute,"energy"::("energy_by_station" in cohort.keys ? list<float>(cohort["energy_by_station"])[chosen] : float(cohort["energy"])),"max_kw"::cohort["max_kw"],"service_until"::1e100,"probe"::false];
                    }
                }
            }
        }
        // Unreceived past issuance and not-yet-issued demand are separate from known exposures.
        // Public train contexts are joint origin/travel/energy/max_kw samples.
        list<float> marks <- list<float>(observation["watermarks"]);
        list<float> rates <- list<float>(observation["rates"]);
        loop stream over: ["unseen_foreground","background"] {
        loop issuer from: 0 to: length(rates)-1 {
            float begin_at <- stream="background" ? now : max(0.0,max(now-ranr_arrival_lookback,marks[issuer]));
            float rate <- rates[issuer];
            float stop_at <- stream="background" ? min(end_at,ranr_warmup+ranr_measure) : now;
            float issuance <- begin_at; int event_index <- 0;
            if rate<=0.0 or empty(ranr_arrival_prior) { continue; }
            loop while: issuance < stop_at {
                int draw <- issuer*100000+event_index+(stream="background" ? 10000000 : 0); event_index <- event_index+1;
                issuance <- issuance-ln(ranr_uniform(311,entity,draw))/rate;
                if issuance >= stop_at { break; }
                list<map<string,unknown>> contexts <- issuer in ranr_contexts_by_issuer.keys ? ranr_contexts_by_issuer[issuer] : [];
                if empty(contexts) { continue; }
                map<string,unknown> context <- contexts[min(length(contexts)-1,int(ranr_uniform(312,entity,draw)*length(contexts)))];
                list<float> travel <- list<float>(context["travel"]);
                int offer <- ranr_categorical(ranr_base(travel),ranr_uniform(314,entity,draw));
                list<float> mass <- ranr_response_mass(travel,offer,"context" in context.keys ? string(context["context"]) : "default");
                if ranr_uniform(328,entity,draw)>ranr_arrival_probability { continue; }
                int chosen <- ranr_categorical(mass,ranr_uniform(313,entity,draw));
                if chosen>=length(travel) { continue; }
                float absolute <- issuance+travel[chosen]*(ranr_eta_factor(entity:entity,draw:draw+1000000));
                if absolute > origin and absolute <= end_at {
                    arrivals << ["sid"::chosen,"at"::absolute,"energy"::("energy_by_station" in context.keys ? list<float>(context["energy_by_station"])[chosen] : float(context["energy"])),"max_kw"::context["max_kw"],"service_until"::1e100,"probe"::false];
                }
            }
        }
        }
        // Received token acknowledgements are observations, not access to true future arrivals.
        if "resolutions" in observation.keys {
            loop resolution over:list<map<string,unknown>>(observation["resolutions"]) {
                float arrived <- "arrival_at" in resolution.keys ? float(resolution["arrival_at"]) : float(resolution["at"]);
                if (resolution["status"]="arrived" or "arrival_at" in resolution.keys) and "energy" in resolution.keys and arrived>origin and arrived<=now {
                    arrivals << ["sid"::resolution["source"],"at"::arrived,"energy"::resolution["energy"],"max_kw"::resolution["max_kw"],"service_until"::(resolution["status"]="cancelled" ? min(("service_until" in resolution.keys ? float(resolution["service_until"]) : 1e100),float(resolution["at"])) : ("service_until" in resolution.keys ? float(resolution["service_until"]) : 1e100)),"probe"::false];
                }
            }
        }
        return arrivals sort_by float(each["at"]);
    }
    list<map<string,unknown>> ranr_future(map<string,unknown> snapshot,map<string,unknown> observation,map<string,unknown> request,int sample) {
        ranr_future_calls <- ranr_future_calls+1;
        list<map<string,unknown>> absolute <- [];
        if ranr_reuse_scenarios and sample in ranr_scenario_cache.keys { absolute <- ranr_scenario_cache[sample]; }
        else { absolute <- ranr_generate_future(observation,request,sample); if ranr_reuse_scenarios { ranr_scenario_cache[sample] <- absolute; } }
        list<map<string,unknown>> result <- [];
        float origin <- float(snapshot["issued"]); int target <- int(snapshot["sid"]);
        loop job over: absolute {
            if int(job["sid"])!=target or float(job["at"])<=origin { continue; }
            map<string,unknown> shifted <- ranr_record(job); shifted["at"] <- float(job["at"])-origin; shifted["service_until"] <- ("service_until" in job.keys ? float(job["service_until"]) : 1e100)-origin;
            result << shifted;
        }
        return result;
    }
    map<string,unknown> ranr_estimate(map<string,unknown> supplied_snapshot,map<string,unknown> observation,map<string,unknown> request) {
        float started <- machine_time;
        if !("snapshots" in observation.keys) { observation <- ranr_record(observation); observation["origin"] <- supplied_snapshot["issued"]; }
        string cache_key <- to_json([observation,request,ranr_method,ranr_horizon,ranr_assumed_defer,ranr_assumed_compliance,ranr_samples,ranr_response_prior,ranr_calibration_source,ranr_arrival_probability,step]);
        if cache_key!=ranr_scenario_cache_key { ranr_scenario_cache <- []; ranr_scenario_cache_key <- cache_key; }
        list<float> waits <- []; list<float> externalities <- []; list<float> charges <- []; list<float> workloads <- [];
        int sid <- int(supplied_snapshot["sid"]); int entity <- int(request["key"]);
        if "energy_by_station" in request.keys { request <- ranr_record(request); request["energy"] <- list<float>(request["energy_by_station"])[sid]; }
        loop sample from: 0 to: ranr_samples-1 {
            map<string,unknown> snapshot <- supplied_snapshot;
            if string(snapshot["source"])="prior" {
                list<map<string,unknown>> pool <- sid in ranr_priors_by_sid.keys ? ranr_priors_by_sid[sid] : [];
                if !empty(pool) { snapshot <- ranr_clone_snapshot(pool[min(length(pool)-1,int(ranr_uniform(320,entity,sample)*length(pool)))]); snapshot["issued"] <- observation["at"]; snapshot["source"] <- "prior"; }
            }
            list<float> powers <- list<float>(snapshot["powers"]);
            list<float> lo <- list<float>(snapshot["release_lo"]); list<float> hi <- list<float>(snapshot["release_hi"]);
            list<float> releases <- [];
            loop j from: 0 to: length(powers)-1 {
                int selected <- min(length(ranr_release_fractions)-1,int(ranr_uniform(321,entity*4099+sample,sid*1000+j)*length(ranr_release_fractions)));
                releases << lo[j]+(hi[j]-lo[j])*ranr_release_fractions[selected];
            }
            list<map<string,unknown>> jobs <- [];
            list<map<string,unknown>> queued <- snapshot["queue"];
            loop job over: queued {
                int selected <- min(length(ranr_energy_fractions)-1,int(ranr_uniform(322,entity*4099+sample,sid*1000+length(jobs))*length(ranr_energy_fractions)));
                float energy <- float(job["low"])+(float(job["high"])-float(job["low"]))*ranr_energy_fractions[selected];
                float service_until <- "service_until" in job.keys ? float(job["service_until"]) : 1e100;
                if "token" in job.keys and "resolutions" in observation.keys {
                    loop resolution over:list<map<string,unknown>>(observation["resolutions"]) {
                        if resolution["token"]=job["token"] and resolution["status"]="cancelled" { service_until <- min(service_until,max(0.0,float(resolution["at"])-float(snapshot["issued"]))); }
                    }
                }
                jobs << ["at"::0.0,"energy"::energy,"max_kw"::job["max_kw"],"service_until"::service_until,"probe"::false];
            }
            float eta <- 0.0;
            if ranr_method!="No-Prediction" {
                float age <- string(supplied_snapshot["source"])="prior" ? 0.0 : max(0.0,float(observation["at"])-float(snapshot["issued"]));
                eta <- age+list<float>(request["travel"])[sid]*(ranr_eta_factor(entity:entity,draw:sample));
                jobs <- jobs+ranr_future(snapshot,observation,request,sample);
            }
            float remaining_observation <- "remaining_observation" in request.keys ? float(request["remaining_observation"]) : 1e100;
            map<string,unknown> probe <- ["at"::eta,"energy"::request["energy"],"max_kw"::request["max_kw"],"service_until"::1e100,"probe"::true];
            list<map<string,unknown>> with_probe <- (jobs+[probe]) sort_by float(each["at"]);
            int probe_index <- with_probe index_of probe;
            map<string,unknown> inserted <- ranr_shadow_limited(powers,releases,with_probe,"aggregate_kw" in snapshot.keys ? float(snapshot["aggregate_kw"]) : sum(powers));
            float waiting <- list<float>(inserted["waits"])[probe_index]; waits << waiting;
            charges << (list<float>(inserted["nominal_services"])[probe_index]>0.0 ? list<float>(inserted["nominal_services"])[probe_index] : 60.0*float(request["energy"])/(charge_efficiency*max(1e-9,min(max(powers),float(request["max_kw"])))));
            workloads << sum(jobs collect float(each["energy"]));
            if ranr_method="No-Prediction" { externalities << 0.0; }
            else {
                float counter_started <- machine_time;
                map<string,unknown> baseline <- ranr_shadow_limited(powers,releases,jobs,"aggregate_kw" in snapshot.keys ? float(snapshot["aggregate_kw"]) : sum(powers));
                externalities << float(inserted["total"])-waiting-float(baseline["total"]);
                ranr_externality_ms <- ranr_externality_ms+machine_time-counter_started;
            }
        }
        float mean_wait <- mean(waits);
        float spread <- sqrt(mean(waits collect ((each-mean_wait)^2)));
        float age <- string(supplied_snapshot["source"])="prior" ? ranr_ttl : max(0.0,float(observation["at"])-float(supplied_snapshot["issued"]));
        ranr_prediction_ms <- ranr_prediction_ms+machine_time-started;
        return ["mean"::mean_wait,"raw_mean"::mean_wait,"charge"::mean(charges),"workload_kwh"::mean(workloads),"congestion_probability"::(float(length(waits where (each>5.0)))/length(waits)),"p95"::ranr_quantile(values:waits,probability:0.95),"externality"::mean(externalities),
            "raw_externality"::mean(externalities),"uncertainty"::(spread+min(age,ranr_ttl)),
            "source"::(ranr_method="No-Prediction" ? "snapshot_fifo_zero" : string(supplied_snapshot["source"]))];
    }
}
