model ranr_math
import "../Mobility.gaml"

global {
    bool ranr_enabled <- true;
    float charge_efficiency <- 0.9;
    list<float> zero_vector(int count) { list<float> result <- []; if count>0 { loop k from:0 to:count-1 { result << 0.0; } } return result; }
    string ranr_method <- "RANR-AW";
    string ranr_project_prefix <- file_exists("../configs/gama/environment.json") ? "../" : "../../";
    map<string,unknown> ranr_environment <- json_file(ranr_project_prefix+"configs/gama/environment.json").contents;
    string ranr_environment_version <- string(ranr_environment["environment_version"]);
    bool have_rush <- true;
    float rush_extra_percent <- float(ranr_environment["rush_extra_percent"]);
    int cars <- int(ranr_environment["cars"]);
    int elecars -> privates+taxis;
    int taxis <- int(ranr_environment["electric_taxis"]);
    int privates <- int(ranr_environment["private_evs"]);
    string ranr_case <- "normal";
    string ranr_run_id <- "gui";
    string ranr_output <- "../outputs/gama_ranr/gui";
    string ranr_parameter_file <- "";
    string ranr_calibration_file <- "";
    bool ranr_development <- false;
    bool ranr_calibrating <- false;
    bool ranr_trace <- true;
    bool ranr_render <- true;
    bool ranr_gui_preview <- false;
    bool ranr_gui_preview_active <- false;
    string ranr_error <- "";
    int ranr_samples <- 32;
    float ranr_warmup <- 360.0;
    float ranr_measure <- 360.0;
    float ranr_deadline <- 360.0;
    float ranr_horizon <- 120.0;
    float ranr_ttl <- 180.0;
    string ranr_observation_version <- "station-observation-3";
    string ranr_objective_version <- "opportunity-service-3";
    float ranr_temperature <- float(ranr_environment["temperature"]);
    float ranr_safety_soc <- float(ranr_environment["safety_soc_reserve"]);
    float ranr_min_send <- float(ranr_environment["min_send_seconds"])/60.0;
    float ranr_event_workload <- float(ranr_environment["event_workload_minutes"]);
    int ranr_event_exposure <- int(ranr_environment["event_exposure_count"]);
    float ranr_failure_beta <- float(ranr_environment["failure_beta"]);
    float ranr_energy_beta <- float(ranr_environment["energy_beta"]);
    string ranr_station_events_file <- "";
    float ranr_duplicate_probability <- 0.0;
    float ranr_partition_begin <- -1.0;
    float ranr_partition_end <- -1.0;
    string ranr_behavior_case <- "moderate";
    string ranr_stabilization <- "off";
    float ranr_smoothing_alpha <- 0.5;
    float ranr_hysteresis_minutes <- 1.0;
    map<string,map<string,unknown>> ranr_response_prior <- [];
    list<float> ranr_policy_latencies <- [];
    map<string,float> ranr_prediction_diagnostics <- [];

    float ranr_ev_speed <- 30.0;
    float ranr_car_speed <- 50.0;
    float ranr_assumed_compliance <- 0.6;
    float ranr_assumed_defer <- 0.05;
    float ranr_arrival_probability <- 1.0;
    float ranr_prior_background_rate <- 0.015;
    float ranr_prior_rate <- 0.06; // Per station/minute; official runs replace with GAMA train calibration.
    float ranr_private_frequency <- float(ranr_environment["private_opportunities_per_day"]);
    float ranr_taxi_frequency <- float(ranr_environment["taxi_opportunities_per_day"]);
    float target_soc <- float(ranr_environment["target_soc"]);
    float ranr_soc_threshold <- float(ranr_environment["eligibility_soc"]);
    list<float> ranr_private_hours <- list<float>(ranr_environment["private_hour_weights"]);
    list<float> ranr_taxi_hours <- list<float>(ranr_environment["taxi_hour_weights"]);
    bool ranr_collect_gui <- false;
    int ranr_collection_seed <- 800001;
    string ranr_collection_status <- "Not collected";
    float ranr_true_compliance <- 0.8;
    float ranr_true_defer <- 0.05;
    float ranr_true_decline <- 0.0;
    float ranr_abandon_after <- -1.0;
    float ranr_delay <- 0.5;
    float ranr_loss <- 0.0;
    float ranr_snapshot_width <- 5.0;
    float ranr_energy_width <- 5.0;
    float ranr_broadcast_period <- float(ranr_environment["broadcast_minutes"]);
    int ranr_burst_size <- 100;
    list<float> ranr_parameters <- [];
    map<string,unknown> ranr_loaded_model <- [];
    bool ranr_candidate_loaded <- false;
    list<float> ranr_scales <- list<float>(ranr_environment["cost_scales"]);
    list<float> ranr_release_fractions <- [0.5];
    list<float> ranr_energy_fractions <- [0.5];
    list<float> ranr_energy_prior <- [20.0];
    list<float> ranr_eta_factors <- [1.0];
    list<float> ranr_sorted_eta <- [1.0];
    list<map<string,unknown>> ranr_prior_snapshots <- [];
    bool ranr_reuse_scenarios <- true;
    string ranr_scenario_cache_key <- "";
    map<int,list<map<string,unknown>>> ranr_scenario_cache <- [];
    map<int,float> ranr_prior_load_by_sid <- [];
    int ranr_scenario_generations <- 0;
    map<int,list<map<string,unknown>>> ranr_contexts_by_issuer <- [];
    map<int,list<map<string,unknown>>> ranr_priors_by_sid <- [];
    list<map<string,unknown>> ranr_arrival_prior <- []; // Train-only public origin-conditioned routing contexts.
    string ranr_calibration_source <- "development";
    list<map<string,unknown>> ranr_terminal_events <- [];
    float ranr_master_seed <- -1.0;
    int ranr_queue_calls <- 0;
    int ranr_future_calls <- 0;
    float ranr_prediction_ms <- 0.0;
    float ranr_externality_ms <- 0.0;
    float ranr_route_ms <- 0.0;
    float ranr_movement_ms <- 0.0;
    float ranr_busy_port_minutes <- 0.0;
    float ranr_policy_ms <- 0.0;
    float ranr_information_ms <- 0.0;
    int ranr_route_hits <- 0;
    string ranr_shell_quote(string value) {
        return "'"+replace(value,"'","'\"'\"'")+"'";
    }
    string ranr_gui_bridge(string operation) {
        file project_directory <- folder(ranr_project_prefix);
        return command("./.venv/bin/python scripts/gui_calibration.py "+operation+" "+ranr_shell_quote(operation="model" ? ranr_parameter_file : ranr_output),project_directory.path);
    }
    action ranr_load_candidate {
        if ranr_candidate_loaded { return nil; }
        if ranr_parameter_file="" and !ranr_development {
            string published <- "../outputs/gama_ranr/models/"+ranr_method+"/parameters.json";
            if file_exists(published) { ranr_parameter_file <- published; }
        }
        if ranr_parameter_file="" {
            if !ranr_development { ranr_error <- "Trained GAMA parameters required; enable Development mode explicitly for fixtures"; return nil; }
            ranr_parameters <- zero_vector(ranr_method="Fixed-Weights" ? 4 : 20);
        } else {
            if !file_exists(ranr_parameter_file) { ranr_error <- "Parameter file does not exist: "+ranr_parameter_file; return nil; }
            ranr_loaded_model <- json_file(ranr_parameter_file).contents;
            if !(ranr_loaded_model["schema"]="gama-ranr-v3" and ranr_loaded_model["backend"]="GAMA" and ranr_loaded_model["method"]=ranr_method) {
                ranr_error <- "Parameter schema/backend/method mismatch"; return nil;
            }
            if string(ranr_loaded_model["environment_version"])!=ranr_environment_version { ranr_error <- "Model environment version mismatch; recalibrate and retrain"; return nil; }
            list<string> features <- ranr_loaded_model["features"];
            if features!=["T_travel_charge","W_mean","W_P95","H","U"] { ranr_error <- "Parameter feature order mismatch"; return nil; }
            if list<string>(ranr_loaded_model["state_features"])!=["bias","load","burst","exposure_uncertainty","age"] { ranr_error <- "Parameter state feature order mismatch"; return nil; }
            if !ranr_development and !bool(ranr_loaded_model["training_completed"]) {
                string validation <- ranr_gui_bridge("candidate");
                if !("CANDIDATE VALID" in validation) { ranr_error <- "Untrained vector requires a registered GAMA evaluation: "+validation; return nil; }
            }
            ranr_parameters <- ranr_loaded_model["parameters"];
            if bool(ranr_loaded_model["training_completed"]) {
                string validation <- ranr_gui_bridge("model");
                if !("MODEL VALID" in validation) { ranr_error <- validation; return nil; }
            }
            // Trained models must match the selected physical environment, never overwrite it.
            if bool(ranr_loaded_model["training_completed"]) {
                map<string,unknown> config <- ranr_loaded_model["config"];
                if int(config["background_cars"])!=cars or int(config["private_evs"])!=privates or int(config["electric_taxis"])!=taxis or
                   float(config["private_frequency"])!=ranr_private_frequency or float(config["taxi_frequency"])!=ranr_taxi_frequency or
                   float(config["initial_hour"])!=initial_hour or float(config["step_seconds"])!=step or
                   float(config["rush_extra_percent"])!=rush_extra_percent or bool(config["rush_enabled"])!=have_rush or
                   float(config["soc_threshold"])!=ranr_soc_threshold or float(config["target_soc"])!=target_soc or
                   float(config["ev_speed_kmh"])!=ranr_ev_speed or float(config["car_speed_kmh"])!=ranr_car_speed or
                   float(config["temperature"])!=ranr_temperature or float(config["p2p_interval"])!=ranr_broadcast_period or float(config["min_send_seconds"])/60.0!=ranr_min_send or
                   string(config["stabilization"])!=ranr_stabilization or string(config["behavior_case"])!=ranr_behavior_case or float(config["failure_beta"])!=ranr_failure_beta or float(config["energy_beta"])!=ranr_energy_beta or
                   int(config["samples"])!=ranr_samples or float(config["deadline_minutes"])!=ranr_deadline {
                    ranr_error <- "Selected configuration differs from trained model"; return nil;
                }
                if ranr_calibration_file!="" and ranr_calibration_file!=string(config["calibration"]) { ranr_error <- "Use the calibration file locked in the model"; return nil; }
                ranr_calibration_file <- string(config["calibration"]);
            }
        }
        if length(ranr_parameters)!=(ranr_method="Fixed-Weights" ? 4 : 20) { ranr_error <- "Invalid dimensions: adaptive methods need 20, Fixed-Weights needs 4"; return nil; }
        loop value over: ranr_parameters { if !(value=value and abs(value)<1e100) { ranr_error <- "Nonfinite parameters"; return nil; } }
        ranr_candidate_loaded <- true;
    }
    // Stable keyed draws. Park-Miller hashing uses products <2^53 (exact doubles).
    // Domains and all keys are explicit; no built-in shared RNG is consumed.
    float ranr_uniform(int domain, int entity, int draw) {
        return keyed_uniform(ranr_master_seed>=0.0 ? ranr_master_seed : float(seed),domain,entity,draw);
    }
    // GAMA 1.9.3 map literals infer a content type; fresh dictionaries prevent
    // later string/count updates from being coerced into character/number lists.
    map<string,unknown> ranr_record(map<string,unknown> input) {
        map<string,unknown> result <- [];
        loop key over: input.keys { result[key] <- input[key]; }
        return result;
    }
    map<string,unknown> ranr_clone_snapshot(map<string,unknown> input) {
        map<string,unknown> result <- ranr_record(input);
        result["powers"] <- copy(input["powers"]);
        result["release_lo"] <- copy(input["release_lo"]);
        result["release_hi"] <- copy(input["release_hi"]);
        if "connectors" in input.keys { result["connectors"] <- copy(input["connectors"]); }
        list<map<string,unknown>> queue <- [];
        list<map<string,unknown>> source <- input["queue"];
        loop job over: source { queue << ranr_record(job); }
        result["queue"] <- queue;
        return result;
    }
    map<string,unknown> ranr_clone_packet(map<string,unknown> input) {
        map<string,unknown> result <- ranr_record(input);
        map<string,unknown> snapshot <- input["snapshot"];
        result["snapshot"] <- ranr_clone_snapshot(snapshot);
        list<map<string,unknown>> cohorts <- [];
        list<map<string,unknown>> source <- input["exposure"];
        loop value over: source {
            map<string,unknown> cohort <- ranr_record(value); cohort["travel"] <- copy(value["travel"]); cohorts << cohort;
        }
        result["exposure"] <- cohorts;
        if "resolutions" in input.keys {
            list<map<string,unknown>> resolutions <- [];
            loop resolution over:list<map<string,unknown>>(input["resolutions"]) { resolutions << ranr_record(resolution); }
            result["resolutions"] <- resolutions;
        }
        return result;
    }
    action ranr_index_calibration {
        ranr_sorted_eta <- ranr_eta_factors sort_by each;
        ranr_contexts_by_issuer <- []; ranr_priors_by_sid <- []; ranr_prior_load_by_sid <- []; ranr_scenario_cache <- []; ranr_scenario_cache_key <- "";
        loop context over: ranr_arrival_prior {
            int issuer <- int(context["issuer"]);
            if !(issuer in ranr_contexts_by_issuer.keys) { ranr_contexts_by_issuer[issuer] <- []; }
            list<map<string,unknown>> values <- ranr_contexts_by_issuer[issuer]; values << context; ranr_contexts_by_issuer[issuer] <- values;
        }
        loop snapshot over: ranr_prior_snapshots {
            int sid <- int(snapshot["sid"]);
            if !(sid in ranr_priors_by_sid.keys) { ranr_priors_by_sid[sid] <- []; }
            list<map<string,unknown>> values <- ranr_priors_by_sid[sid]; values << snapshot; ranr_priors_by_sid[sid] <- values;
        }
        loop sid over: ranr_priors_by_sid.keys { list<map<string,unknown>> pool <- ranr_priors_by_sid[sid]; ranr_prior_load_by_sid[sid] <- mean(pool collect ranr_snapshot_load(each)); }
    }
    float ranr_snapshot_load(map<string,unknown> snapshot) {
        list<float> powers <- snapshot["powers"];
        list<float> lo <- snapshot["release_lo"]; list<float> hi <- snapshot["release_hi"];
        list<map<string,unknown>> queue <- snapshot["queue"];
        float energy <- sum(queue collect ((float(each["low"])+float(each["high"]))/2.0));
        return (sum(lo)+sum(hi))/(2.0*max(1,length(powers))*60.0)+energy/(charge_efficiency*max(1e-9,sum(powers)));
    }
    float ranr_normal(int domain,int entity,int draw) {
        return sqrt(-2.0*ln(ranr_uniform(domain,entity,2*draw)))*cos(360.0*ranr_uniform(domain,entity,2*draw+1));
    }
    float ranr_eta_factor(int entity,int draw) {
        assert !empty(ranr_eta_factors);
        return ranr_eta_factors[min(length(ranr_eta_factors)-1,int(ranr_uniform(324,entity,draw)*length(ranr_eta_factors)))];
    }
    list<float> ranr_feasible_travel(map<string,unknown> request,map<string,unknown> observation) {
        list<float> travel <- copy(list<float>(request["travel"]));
        list<map<string,unknown>> snapshots <- observation["snapshots"];
        loop sid from:0 to:length(travel)-1 {
            map<string,unknown> snapshot <- snapshots[sid];
            if ("operational" in snapshot.keys and !bool(snapshot["operational"])) or
               ("connectors" in snapshot.keys and "connector" in request.keys and !(string(request["connector"]) in list<string>(snapshot["connectors"]))) or
               sum(list<float>(snapshot["powers"]))<=0.0 { travel[sid] <- -1.0; }
        }
        return travel;
    }
    list<float> ranr_response_mass(list<float> travel,int recommended,string context) {
        list<float> mass <- ranr_base(travel) collect ((1.0-ranr_assumed_defer)*(1.0-ranr_assumed_compliance)*each);
        if recommended>=0 and recommended<length(mass) { mass[recommended] <- mass[recommended]+(1.0-ranr_assumed_defer)*ranr_assumed_compliance; }
        mass << ranr_assumed_defer;
        if !(context in ranr_response_prior.keys) and "default" in ranr_response_prior.keys { context <- "default"; }
        if context in ranr_response_prior.keys {
            map<string,unknown> prior <- ranr_response_prior[context];
            float other <- float(prior["other"]); float follow <- float(prior["match"]); float outside <- float(prior["outside"]);
            list<float> alternative <- ranr_base(travel); if recommended>=0 { alternative[recommended] <- 0.0; }
            float available <- sum(alternative);
            mass <- available>0.0 ? alternative collect (other*each/available) : zero_vector(length(travel));
            if recommended>=0 { mass[recommended] <- mass[recommended]+follow+(available<=0.0 ? other : 0.0); }
            mass << outside;
        }
        float total <- sum(mass); return total>0.0 ? mass collect (each/total) : mass;
    }
    // Bayes: B~Bernoulli(p), other anonymous arrivals~Poisson(lambda), A=B+other.
    // The Poisson model for other cohorts is a declared mean-field approximation.
    float ranr_seen_posterior(float probability,int observed,float other_mean) {
        if observed<=0 or probability<=0.0 { return 0.0; }
        if probability>=1.0 { return 1.0; }
        float a <- probability*observed; float b <- (1.0-probability)*max(0.0,other_mean);
        return a/max(1e-12,a+b);
    }
    list<float> ranr_outstanding_mass(map<string,unknown> cohort,float at) {
        list<float> travel <- list<float>(cohort["travel"]);
        int recommended <- int(cohort["recommended"]);
        list<float> mass <- ranr_response_mass(travel,recommended,"context" in cohort.keys ? string(cohort["context"]) : "default");
        remove index:length(mass)-1 from:mass;
        if "resolved" in cohort.keys and bool(cohort["resolved"]) { return zero_vector(length(travel)); }
        loop sid from: 0 to: length(travel)-1 {
            if travel[sid]<=0.0 { mass[sid] <- 0.0; continue; }
            float ratio <- max(0.0,at-float(cohort["issued"]))/travel[sid];
            int low <- 0; int high <- length(ranr_sorted_eta);
            loop while: low<high {
                int middle <- int(floor((low+high)/2.0));
                if ranr_sorted_eta[middle]<=ratio { low <- middle+1; } else { high <- middle; }
            }
            mass[sid] <- mass[sid]*(1.0-float(low)/length(ranr_sorted_eta));
        }
        return mass collect (each*ranr_arrival_probability);
    }
    int ranr_categorical(list<float> probabilities,float uniform) {
        float cumulative <- 0.0;
        loop k from: 0 to: length(probabilities)-1 {
            cumulative <- cumulative+probabilities[k];
            if uniform < cumulative { return k; }
        }
        return length(probabilities)-1;
    }
    list<float> ranr_softmax(list<float> logits) {
        assert !empty(logits);
        float top <- max(logits);
        list<float> values <- logits collect exp(each-top);
        float total <- sum(values); assert total > 0.0;
        return values collect (each/total);
    }
    list<float> ranr_base(list<float> travel) {
        list<float> values <- travel collect (each < 0.0 ? 0.0 : exp(-each/15.0));
        float total <- sum(values);
        return total > 0.0 ? (values collect (each/total)) : values;
    }
    list<float> ranr_weights(list<float> state) {
        assert length(state)=5;
        int count <- ranr_method="Fixed-Weights" ? 4 : 20;
        assert length(ranr_parameters)=count;
        list<float> logits <- [];
        loop k from: 0 to: 3 {
            float value <- 0.0;
            if ranr_method="Fixed-Weights" { value <- ranr_parameters[k]; }
            else { loop j from: 0 to: 4 { value <- value+ranr_parameters[k*5+j]*state[j]; } }
            logits << value;
        }
        logits << 0.0;
        return ranr_softmax(logits);
    }
    float ranr_quantile(list<float> values,float probability) {
        assert !empty(values);
        list<float> ordered <- values sort_by each;
        float position <- probability*(length(ordered)-1);
        int lo <- int(floor(position)); int hi <- int(ceil(position));
        return ordered[lo]+(position-lo)*(ordered[hi]-ordered[lo]);
    }
    // Strict FIFO heterogeneous independent ports, including EV acceptance limits.
    map<string,unknown> ranr_shadow(list<float> powers,list<float> releases,list<map<string,unknown>> jobs) {
        assert length(powers)>0 and length(powers)=length(releases);
        list<float> free_at <- copy(releases);
        loop j from:0 to:length(powers)-1 { if powers[j]<=0.0 { free_at[j] <- 1e100; } } list<float> waits <- []; list<float> starts <- []; list<float> services <- []; list<float> nominal <- []; list<float> delivered <- [];
        float last_start <- 0.0; float tick <- step/60.0;
        loop job over: jobs {
            float arrival <- tick*ceil(float(job["at"])/tick-1e-10);
            float lower <- max(arrival,last_start); int selected <- 0;
            loop j from: 1 to: length(powers)-1 {
                if length(powers)=1 { break; }
                float a <- max(free_at[j],lower); float b <- max(free_at[selected],lower);
                if a < b-1e-10 or (abs(a-b)<=1e-10 and (min(powers[j],float(job["max_kw"]))>min(powers[selected],float(job["max_kw"])) or (min(powers[j],float(job["max_kw"]))=min(powers[selected],float(job["max_kw"])) and powers[j]>powers[selected]))) { selected <- j; }
            }
            float begin <- max(free_at[selected],lower);
            if max(powers)<=0.0 { begin <- 1e100; }
            float deadline <- "deadline" in job.keys ? float(job["deadline"]) : 1e100;
            if begin>=deadline {
                starts << deadline; nominal << 0.0; services << 0.0; delivered << 0.0; waits << max(0.0,deadline-arrival); last_start <- max(last_start,deadline); continue;
            }
            float service_minutes <- 60.0*float(job["energy"])/(charge_efficiency*min(powers[selected],float(job["max_kw"])));
            free_at[selected] <- min(deadline,begin+tick*max(1.0,ceil(service_minutes/tick-1e-10)));
            nominal << service_minutes; services << max(0.0,min(service_minutes,deadline-begin)); delivered << min(float(job["energy"]),max(0.0,deadline-begin)*charge_efficiency*min(powers[selected],float(job["max_kw"]))/60.0);
            starts << begin; waits << max(0.0,begin-arrival); last_start <- begin;
        }
        ranr_queue_calls <- ranr_queue_calls+1;
        return ["free"::free_at,"waits"::waits,"starts"::starts,"total"::sum(waits),"services"::services,"nominal_services"::nominal,"delivered"::delivered];
    }
}
