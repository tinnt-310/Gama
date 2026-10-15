model ranr_math
import "../StationForecast.gaml"

global {
    bool ranr_enabled <- false;
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
    float ranr_temperature <- 0.2;
    float ranr_ev_speed <- 30.0;
    float ranr_car_speed <- 50.0;
    float ranr_assumed_compliance <- 0.6;
    float ranr_assumed_defer <- 0.05;
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
    float ranr_delay <- 0.5;
    float ranr_loss <- 0.0;
    float ranr_snapshot_width <- 5.0;
    float ranr_energy_width <- 5.0;
    float ranr_broadcast_period <- 5.0;
    int ranr_burst_size <- 100;
    list<float> ranr_parameters <- [];
    map<string,unknown> ranr_loaded_model <- [];
    bool ranr_candidate_loaded <- false;
    list<float> ranr_scales <- [30.0,60.0,120.0,120.0,60.0];
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
            if !(ranr_loaded_model["schema"]="gama-ranr-v2" and ranr_loaded_model["backend"]="GAMA" and ranr_loaded_model["method"]=ranr_method) {
                ranr_error <- "Parameter schema/backend/method mismatch"; return nil;
            }
            if string(ranr_loaded_model["environment_version"])!=ranr_environment_version { ranr_error <- "Model environment version mismatch; recalibrate and retrain"; return nil; }
            list<string> features <- ranr_loaded_model["features"];
            if features!=["T","W_mean","W_P95","H","U"] { ranr_error <- "Parameter feature order mismatch"; return nil; }
            if list<string>(ranr_loaded_model["state_features"])!=["bias","load","burst","exposure_uncertainty","age"] { ranr_error <- "Parameter state feature order mismatch"; return nil; }
            bool gui_mode <- ranr_run_id="gui" or "gui_" in ranr_run_id;
            if gui_mode and !ranr_development and !bool(ranr_loaded_model["training_completed"]) {
                ranr_error <- "GUI requires a GAMA-trained model selected by long validation"; return nil;
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
        return (sum(lo)+sum(hi))/(2.0*length(powers)*60.0)+energy/(charge_efficiency*sum(powers));
    }
    float ranr_normal(int domain,int entity,int draw) {
        return sqrt(-2.0*ln(ranr_uniform(domain,entity,2*draw)))*cos(360.0*ranr_uniform(domain,entity,2*draw+1));
    }
    float ranr_eta_factor(int entity,int draw) {
        assert !empty(ranr_eta_factors);
        return ranr_eta_factors[min(length(ranr_eta_factors)-1,int(ranr_uniform(324,entity,draw)*length(ranr_eta_factors)))];
    }
    list<float> ranr_outstanding_mass(map<string,unknown> cohort,float at) {
        list<float> travel <- list<float>(cohort["travel"]);
        list<float> mass <- ranr_base(travel) collect ((1.0-ranr_assumed_defer)*(1.0-ranr_assumed_compliance)*each);
        int recommended <- int(cohort["recommended"]);
        mass[recommended] <- mass[recommended]+(1.0-ranr_assumed_defer)*ranr_assumed_compliance;
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
        return mass;
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
        list<float> free_at <- copy(releases); list<float> waits <- []; list<float> starts <- [];
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
            float deadline <- "deadline" in job.keys ? float(job["deadline"]) : 1e100;
            if begin>=deadline {
                starts << deadline; waits << max(0.0,deadline-arrival); last_start <- max(last_start,deadline); continue;
            }
            float service_minutes <- 60.0*float(job["energy"])/(charge_efficiency*min(powers[selected],float(job["max_kw"])));
            free_at[selected] <- min(deadline,begin+tick*max(1.0,ceil(service_minutes/tick-1e-10)));
            starts << begin; waits << max(0.0,begin-arrival); last_start <- begin;
        }
        ranr_queue_calls <- ranr_queue_calls+1;
        return ["free"::free_at,"waits"::waits,"starts"::starts,"total"::sum(waits)];
    }
}
