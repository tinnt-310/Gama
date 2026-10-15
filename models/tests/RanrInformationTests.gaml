model ranr_information_tests
import "../ranr/Policy.gaml"
global {
    geometry shape <- rectangle(100,100);
    init {
        ranr_parameters <- zero_vector(20); ranr_samples <- 8; ranr_method <- "No-Prediction";
        create ranr_station_agent number:2 { ranr_sid <- index; }
        map<string,unknown> local <- ["sid"::0,"issued"::0.0,"powers"::[60.0],"release_lo"::[0.0],"release_hi"::[0.0],"queue"::[],"source"::"local"];
        map<string,unknown> remote <- ["sid"::1,"issued"::0.0,"powers"::[60.0],"release_lo"::[10.0],"release_hi"::[20.0],"queue"::[],"source"::"local"];
        list<map<string,unknown>> priors <- [ranr_clone_snapshot(local),ranr_clone_snapshot(local)]; priors[1]["sid"] <- 1;
        loop prior over: priors { prior["source"] <- "prior"; }
        ranr_station_agent[0].ranr_local_snapshot <- local;
        map<string,unknown> packet <- ranr_record(["sender"::1,"sequence"::1,"issued"::0.0,"snapshot"::copy(remote),"exposure"::[],"rate"::0.1]);
        ask ranr_station_agent[0] { do ranr_receive(packet,1.0); }
        map<string,unknown> observed <- ranr_station_agent[0].ranr_observe(1.0,priors);
        list<map<string,unknown>> snapshots <- observed["snapshots"];
        assert snapshots[1]["source"]="peer" and float(snapshots[1]["issued"])=0.0;
        // Delivered packet is a frozen value even if the sender changes its original map.
        map<string,unknown> changed <- packet["snapshot"]; changed["release_lo"] <- [999.0];
        observed <- ranr_station_agent[0].ranr_observe(1.0,priors); snapshots <- observed["snapshots"];
        assert list<float>(snapshots[1]["release_lo"])=[10.0];
        packet["sequence"] <- 0;
        assert packet["sequence"] is int;
        ask ranr_station_agent[0] { do ranr_receive(packet,2.0); }
        assert ranr_station_agent[0].ranr_received_sequence[1]=1;
        ranr_method <- "No-P2P";
        observed <- ranr_station_agent[0].ranr_observe(2.0,priors); snapshots <- observed["snapshots"];
        assert snapshots[1]["source"]="prior" and list<float>(snapshots[1]["release_lo"])=[0.0];
        ranr_method <- "No-Prediction";
        map<string,unknown> request <- ["key"::123,"energy"::9.0,"max_kw"::60.0,"travel"::[1.0,2.0]];
        observed <- ranr_station_agent[0].ranr_observe(2.0,priors);
        map<string,unknown> result <- ranr_station_agent[0].ranr_recommend(request,observed);
        assert length(list(result["weights"]))=5 and length(list(result["probabilities"]))=2;
        int exposure_count <- length(ranr_station_agent[0].ranr_local_exposure);
        map<string,unknown> retry <- ranr_station_agent[0].ranr_recommend(request,observed);
        assert result=retry and length(ranr_station_agent[0].ranr_local_exposure)=exposure_count;
        // A second demand in the same cohort updates scalar fields without
        // converting them to lists; retry remains idempotent.
        map<string,unknown> next_request <- ranr_record(request);
        next_request["key"] <- 124; next_request["travel"] <- [1.0,-1.0];
        map<string,unknown> first_aggregate <- ranr_station_agent[0].ranr_recommend(next_request,observed);
        next_request["key"] <- 125;
        map<string,unknown> second_aggregate <- ranr_station_agent[0].ranr_recommend(next_request,observed);
        list<map<string,unknown>> cohorts <- list(ranr_station_agent[0].ranr_local_exposure.values) where (each["count"]=2);
        assert first_aggregate["selected"]=0 and second_aggregate["selected"]=0;
        assert length(cohorts)=1 and cohorts[0]["version"]=2;
        assert cohorts[0]["count"] is int and cohorts[0]["version"] is int;
        assert cohorts[0]["issued"] is float and cohorts[0]["energy"] is float;
        assert cohorts[0]["travel"] is list;
        ranr_station_agent[0].ranr_request_cache <- [];
        ranr_true_compliance <- 0.0; ranr_true_defer <- 1.0;
        map<string,unknown> hidden_changed <- ranr_station_agent[0].ranr_recommend(request,observed);
        assert result["probabilities"]=hidden_changed["probabilities"];
        assert ranr_future_calls=0;
        write "RANR_INFORMATION_PASS";
    }
}
experiment "ranr_information" type:gui { float seed <- 900001.0; }
