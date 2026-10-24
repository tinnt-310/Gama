model ranr_prediction_benchmark_sharded
import "/home/tinnt/Gama_Workspace/Nha Trang CSs planning/models/ranr/Policy.gaml"
global {
    geometry shape <- rectangle(100,100);
    string probe_output <- "../../outputs/gama_ranr/probes.csv";
    bool ranr_reuse_scenarios <- false;
    string ranr_project_prefix <- "/home/tinnt/Gama_Workspace/Nha Trang CSs planning/";
    string selected_method <- "";
    int selected_station <- -1;
    int selected_probe <- -1;
    init {
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
                    map<string,unknown> estimate <- ranr_estimate(snapshot,observation,request);
                    rows <- rows+method+","+sid+","+probe+","+estimate["mean"]+","+estimate["p95"]+","+estimate["externality"]+","+ranr_queue_calls+"\n";
                }
            }
        }
        save rows to: probe_output format:"text";
        write "RANR_PREDICTION_BENCHMARK_PASS";
    }
}
experiment "ranr_prediction_benchmark" type:gui {
    float seed <- 900001.0;
    parameter "Output" var:probe_output;
    parameter "Calibration" var:ranr_calibration_file;
    parameter "Samples" var:ranr_samples;
    parameter "Selected method" var:selected_method;
    parameter "Selected station" var:selected_station;
    parameter "Selected probe" var:selected_probe;
}
