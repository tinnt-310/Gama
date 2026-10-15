model ranr_microbenchmark
import "../ranr/Policy.gaml"
global {
    geometry shape <- rectangle(100,100);
    string benchmark_output <- "../../outputs/gama_ranr/microbenchmark.json";
    init {
        ranr_samples <- 8; ranr_parameters <- zero_vector(20);
        create ranr_station_agent { ranr_sid <- 0; }
        map<string,unknown> snapshot <- ranr_record(["sid"::0,"issued"::0.0,"powers"::[60.0,11.0],"release_lo"::[5.0,10.0],"release_hi"::[10.0,15.0],"queue"::[["low"::10.0,"high"::15.0,"max_kw"::60.0]],"source"::"peer"]);
        map<string,unknown> observation <- ranr_record(["at"::2.0,"snapshots"::[snapshot],"exposure"::[],"watermarks"::[0.0],"rates"::[0.0]]);
        list<map<string,unknown>> rows <- [];
        loop method over:["RANR-AW","No-P2P","No-Prediction","Fixed-Weights"] {
            ranr_method <- method; ranr_parameters <- zero_vector(method="Fixed-Weights" ? 4 : 20);
            ranr_station_agent[0].ranr_request_cache <- []; ranr_policy_latencies <- [];
            loop k from:1 to:8 {
                map<string,unknown> request <- ranr_record(["key"::k,"energy"::9.0,"max_kw"::60.0,"travel"::[5.0]]);
                map<string,unknown> result <- ranr_station_agent[0].ranr_recommend(request,observation);
                assert abs(sum(list<float>(result["probabilities"]))-1.0)<1e-9;
            }
            rows << ["method"::method,"samples"::ranr_samples,"requests"::8,"mean_ms"::mean(ranr_policy_latencies),"p95_ms"::ranr_quantile(ranr_policy_latencies,0.95),"max_ms"::max(ranr_policy_latencies),"queue_calls_cumulative"::ranr_queue_calls];
        }
        save rows to:benchmark_output format:"json";
        write "RANR_MICROBENCHMARK_PASS";
    }
}
experiment "ranr_microbenchmark" type:gui { parameter "Output" var:benchmark_output; }
