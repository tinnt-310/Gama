model ranr_scenario_cache_tests
import "../ranr/Policy.gaml"
global {
    geometry shape <- rectangle(100,100);
    init {
        ranr_method <- "RANR-AW"; ranr_samples <- 16; ranr_warmup <- 100.0; ranr_measure <- 500.0;
        map<string,unknown> snapshot <- ["sid"::0,"issued"::100.0,"powers"::[60.0,11.0],"release_lo"::[10.0,20.0],"release_hi"::[15.0,25.0],"queue"::[],"source"::"peer"];
        map<string,unknown> second <- ranr_clone_snapshot(snapshot); second["sid"] <- 1;
        ranr_arrival_prior <- [["issuer"::0,"travel"::[5.0,10.0],"energy"::9.0,"max_kw"::60.0],["issuer"::1,"travel"::[10.0,5.0],"energy"::9.0,"max_kw"::60.0]];
        do ranr_index_calibration;
        map<string,unknown> cohort <- ["key"::23,"recommended"::0,"count"::10,"issued"::99.0,"expires"::200.0,"travel"::[5.0,10.0],"energy"::9.0,"max_kw"::60.0];
        map<string,unknown> observation <- ["at"::105.0,"snapshots"::[snapshot,second],"exposure"::[cohort],"watermarks"::[100.0,100.0],"rates"::[0.1,0.1]];
        map<string,unknown> request <- ["key"::111,"energy"::9.0,"max_kw"::60.0,"travel"::[5.0,10.0]];
        ranr_reuse_scenarios <- false;
        map<string,unknown> reference <- ranr_estimate(snapshot,observation,request);
        ranr_reuse_scenarios <- true;ranr_scenario_cache <- [];ranr_scenario_cache_key <- "";
        map<string,unknown> optimized <- ranr_estimate(snapshot,observation,request);
        assert abs(float(reference["mean"])-float(optimized["mean"]))<1e-9;
        assert abs(float(reference["p95"])-float(optimized["p95"]))<1e-9;
        assert abs(float(reference["raw_externality"])-float(optimized["raw_externality"]))<1e-9;
        int before <- ranr_scenario_generations;
        optimized <- ranr_estimate(second,observation,request);
        assert ranr_scenario_generations=before;
        write "RANR_SCENARIO_CACHE_PASS";
    }
}
experiment "ranr_scenario_cache" type:gui { float seed <- 900001.0; }
