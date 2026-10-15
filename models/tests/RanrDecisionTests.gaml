model ranr_decision_tests
import "../ranr/Policy.gaml"
global {
    geometry shape <- rectangle(100,100);
    init {
        ranr_method <- "No-Prediction"; ranr_parameters <- zero_vector(20); ranr_samples <- 8;
        create ranr_station_agent { ranr_sid <- 0; }
        map<string,unknown> a <- ranr_record(["sid"::0,"issued"::0.0,"powers"::[60.0],"release_lo"::[0.0],"release_hi"::[0.0],"queue"::[],"source"::"local","operational"::true,"connectors"::["generic-public"]]);
        map<string,unknown> b <- ranr_clone_snapshot(a); b["sid"] <- 1; b["powers"] <- [120.0];
        map<string,unknown> observation <- ranr_record(["at"::0.0,"snapshots"::[a,b],"exposure"::[],"watermarks"::[0.0,0.0],"rates"::[0.0,0.0]]);
        map<string,unknown> request <- ranr_record(["key"::1,"energy"::9.0,"max_kw"::120.0,"travel"::[1.0,1.0],"connector"::"generic-public"]);
        map<string,unknown> result <- ranr_station_agent[0].ranr_recommend(request,observation);
        list<map<string,unknown>> estimates <- result["estimates"];
        assert float(estimates[0]["charge"])=10.0 and float(estimates[1]["charge"])=5.0;
        list<list<float>> features <- result["raw_features"];
        assert features[0][0]=11.0 and features[1][0]=6.0;
        assert list<float>(result["costs"])[0]>list<float>(result["costs"])[1];
        assert ranr_future_calls=0;
        b["operational"] <- false; request["key"] <- 2;
        result <- ranr_station_agent[0].ranr_recommend(request,observation);
        assert list<float>(result["probabilities"])[1]=0.0;
        b["operational"] <- true; b["connectors"] <- ["incompatible"]; request["key"] <- 3;
        result <- ranr_station_agent[0].ranr_recommend(request,observation);
        assert list<float>(result["probabilities"])[1]=0.0;
        request["travel"] <- [-1.0,-1.0]; request["key"] <- 4;
        result <- ranr_station_agent[0].ranr_recommend(request,observation);
        assert result["selected"]=-1 and sum(list<float>(result["probabilities"]))=0.0;
        assert 4 in ranr_station_agent[0].ranr_request_cache.keys;
        ranr_stabilization <- "smoothing";
        ranr_station_agent[0].ranr_forecast_history["test"] <- ["mean"::99.0];
        map<string,unknown> packet <- ranr_record(["sender"::1,"sequence"::1,"issued"::0.0,"snapshot"::b,"exposure"::[],"critical"::true]);
        ask ranr_station_agent[0] { do ranr_receive(packet,0.0); }
        assert empty(ranr_station_agent[0].ranr_forecast_history);
        write "RANR_DECISION_PASS";
    }
}
experiment "ranr_decision" type:gui;
