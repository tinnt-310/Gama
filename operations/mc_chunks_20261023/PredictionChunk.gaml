model ranr_prediction_benchmark_sharded
import "/home/tinnt/Gama_Workspace/Nha Trang CSs planning/models/ranr/Policy.gaml"
global {
    map<string,unknown> ranr_estimate_chunk(map<string,unknown> supplied_snapshot,map<string,unknown> observation,map<string,unknown> request) {
        float started <- machine_time;
        if !("snapshots" in observation.keys) { observation <- ranr_record(observation); observation["origin"] <- supplied_snapshot["issued"]; }
        string cache_key <- to_json([observation,request,ranr_method,ranr_horizon,ranr_assumed_defer,ranr_assumed_compliance,ranr_samples,ranr_response_prior,ranr_calibration_source,ranr_arrival_probability,step]);
        if cache_key!=ranr_scenario_cache_key { ranr_scenario_cache <- []; ranr_scenario_cache_key <- cache_key; }
        list<float> waits <- []; list<float> externalities <- []; list<float> charges <- []; list<float> workloads <- [];
        int sid <- int(supplied_snapshot["sid"]); int entity <- int(request["key"]);
        if "energy_by_station" in request.keys { request <- ranr_record(request); request["energy"] <- list<float>(request["energy_by_station"])[sid]; }
        loop sample from: sample_begin to: sample_end-1 {
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
        return ["sample_waits"::waits,"sample_externalities"::externalities,"mean"::mean_wait,"raw_mean"::mean_wait,"charge"::mean(charges),"workload_kwh"::mean(workloads),"congestion_probability"::(float(length(waits where (each>5.0)))/length(waits)),"p95"::ranr_quantile(values:waits,probability:0.95),"externality"::mean(externalities),
            "raw_externality"::mean(externalities),"uncertainty"::(spread+min(age,ranr_ttl)),
            "source"::(ranr_method="No-Prediction" ? "snapshot_fifo_zero" : string(supplied_snapshot["source"]))];
    }
    int sample_begin <- 0;
    int sample_end <- 0;
    string raw_output <- "";
    geometry shape <- rectangle(100,100);
    string probe_output <- "../../outputs/gama_ranr/probes.csv";
    bool ranr_reuse_scenarios <- false;
    string ranr_project_prefix <- "/home/tinnt/Gama_Workspace/Nha Trang CSs planning/";
    string selected_method <- "";
    int selected_station <- -1;
    int selected_probe <- -1;
    init {
        assert sample_begin>=0 and sample_end>sample_begin and sample_end<=ranr_samples;
        assert selected_method!="" and selected_station>=0 and selected_probe>=0;
        list<map<string,unknown>> raw_rows <- [];
        assert file_exists(ranr_calibration_file);
        map<string,unknown> calibration <- json_file(ranr_calibration_file).contents;
        assert calibration["backend"]="GAMA" and calibration["split"]="train";
        ranr_release_fractions <- calibration["release_fractions"];
        ranr_energy_fractions <- calibration["energy_fractions"];
        ranr_arrival_probability <- float(calibration["arrival_probability"]);
        ranr_eta_factors <- calibration["eta_factors"];
        ranr_response_prior <- calibration["response_prior"];
        ranr_prior_snapshots <- calibration["prior_snapshots"];
        ranr_arrival_prior <- calibration["arrival_prior"];
        ranr_prior_rate <- float(calibration["request_rate"]);
        ranr_prior_background_rate <- float(calibration["background_rate"]);
        do ranr_index_calibration;
        string rows <- "method,station,probe,mean,p95,externality,queue_calls\n";
        loop method over: ["RANR-AW","No-P2P","No-Prediction"] {
            if selected_method!="" and selected_method!=method { continue; }
            ranr_method <- method;
            loop sid from: 0 to: 10 {
                if selected_station>=0 and selected_station!=sid { continue; }
                list<map<string,unknown>> pool <- ranr_prior_snapshots where (int(each["sid"])=sid);
                loop probe from: 0 to: 4 {
                    if selected_probe>=0 and selected_probe!=probe { continue; }
                    map<string,unknown> snapshot <- ranr_clone_snapshot(pool[int(probe*(length(pool)-1)/4)]);
                    snapshot["source"] <- method="No-P2P" ? "prior" : "peer";
                    snapshot["issued"] <- 100.0;
                    if probe=2 or probe=4 {
                        list<map<string,unknown>> queue <- copy(list(snapshot["queue"]));
                        loop k from: 1 to: 30 { queue << ["low"::15.0,"high"::25.0,"max_kw"::60.0,"deadline"::360.0]; }
                        snapshot["queue"] <- queue;
                    }
                    map<string,unknown> request <- ["key"::(sid*100+probe),"energy"::20.0,"max_kw"::120.0,"travel"::zero_vector(11)];
                    request["travel"] <- zero_vector(11) collect 20.0;
                    map<string,unknown> observation <- ["at"::(100.0+probe*30.0),"exposure"::[],"watermarks"::zero_vector(11) collect 100.0,"rates"::zero_vector(11) collect ranr_prior_rate];
                    if probe>=3 and method!="No-Prediction" {
                        list<map<string,unknown>> cohorts <- [];
                        loop k from:1 to:(probe=3 ? 100 : 200) { cohorts << ["key"::k,"token"::("probe_"+k),"recommended"::sid,"sender"::sid,"context"::"default","count"::1,"version"::1,"issued"::100.0,"expires"::460.0,"travel"::copy(request["travel"]),"energy"::20.0,"max_kw"::120.0]; }
                        observation["exposure"] <- cohorts;
                    }
                    map<string,unknown> estimate <- ranr_estimate_chunk(snapshot,observation,request);
                    raw_rows << ["method"::method,"station"::sid,"probe"::probe,"sample_begin"::sample_begin,"sample_end"::sample_end,"configured_samples"::ranr_samples,"waits"::estimate["sample_waits"],"externalities"::estimate["sample_externalities"],"queue_calls"::ranr_queue_calls];
                    rows <- rows+method+","+sid+","+probe+","+estimate["mean"]+","+estimate["p95"]+","+estimate["externality"]+","+ranr_queue_calls+"\n";
                }
            }
        }
        save rows to: probe_output format:"text";
        assert length(raw_rows)=1;
        save raw_rows to:raw_output format:"json";
        write "RANR_PREDICTION_BENCHMARK_PASS";
    }
}
experiment "ranr_prediction_benchmark" type:gui {
    float seed <- 900001.0;
    parameter "Output" var:probe_output;
    parameter "Calibration" var:ranr_calibration_file;
    parameter "Samples" var:ranr_samples;
    parameter "Sample begin" var:sample_begin;
    parameter "Sample end" var:sample_end;
    parameter "Raw output" var:raw_output;
    parameter "Selected method" var:selected_method;
    parameter "Selected station" var:selected_station;
    parameter "Selected probe" var:selected_probe;
}
