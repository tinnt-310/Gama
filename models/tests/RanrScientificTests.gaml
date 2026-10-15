model ranr_scientific_tests
import "../ranr/Policy.gaml"
global {
    geometry shape <- rectangle(100,100);
    init {
        ranr_parameters <- zero_vector(20);
        map<string,unknown> snapshot <- ["sid"::0,"issued"::0.0,"powers"::[60.0],"release_lo"::[10.0],"release_hi"::[20.0],
            "queue"::[["low"::5.0,"high"::15.0,"max_kw"::60.0]],"source"::"local"];
        map<string,unknown> request <- ["key"::1,"energy"::9.0,"max_kw"::60.0,"travel"::[5.0]];
        map<string,unknown> observation <- ["at"::0.0,"snapshots"::[snapshot],"exposure"::[],"watermarks"::[0.0],"rates"::[0.0]];
        ranr_method <- "No-Prediction"; ranr_samples <- 128;
        ranr_release_fractions <- [0.1,0.9]; ranr_energy_fractions <- [0.1,0.9];
        map<string,unknown> estimate <- ranr_estimate(snapshot,observation,request);
        assert float(estimate["p95"])>float(estimate["mean"])+1.0;
        assert float(estimate["externality"])=0.0 and string(estimate["source"])="snapshot_fifo_zero";
        assert ranr_future_calls=0;
        snapshot["release_hi"] <- [10.0]; snapshot["queue"] <- [["low"::9.0,"high"::9.0,"max_kw"::60.0]];
        estimate <- ranr_estimate(snapshot,observation,request);
        assert abs(float(estimate["p95"])-float(estimate["mean"]))<1e-9;
        map<string,unknown> baseline <- ranr_shadow([60.0],[0.0],[["at"::5.0,"energy"::9.0,"max_kw"::60.0]]);
        map<string,unknown> inserted <- ranr_shadow([60.0],[0.0],[["at"::0.0,"energy"::9.0,"max_kw"::60.0],["at"::5.0,"energy"::9.0,"max_kw"::60.0]]);
        assert abs(float(inserted["total"])-float(baseline["total"])-5.0)<1e-9;
        map<string,unknown> fifo <- ranr_shadow([60.0],[0.0],[["at"::0.0,"energy"::9.0,"max_kw"::60.0],["at"::0.0,"energy"::9.0,"max_kw"::60.0]]);
        assert list<float>(fifo["starts"])=[0.0,10.0];
        ranr_method <- "Fixed-Weights"; ranr_parameters <- [1.0,2.0,3.0,4.0];
        list<float> fixed <- ranr_weights([1.0,0.0,0.0,0.0,0.0]);
        assert fixed=ranr_weights([1.0,1.0,1.0,1.0,1.0]) and length(fixed)=5 and abs(sum(fixed)-1.0)<1e-10;
        ranr_method <- "No-Prediction"; ranr_parameters <- zero_vector(20);
        assert length(ranr_weights([1.0,0.0,0.0,0.0,0.0]))=5;
        list<float> uniforms <- []; loop k from: 1 to: 10000 { uniforms << ranr_uniform(101,k,0); }
        assert abs(mean(uniforms)-0.5)<0.02;
        assert abs(mean(uniforms collect ((each-0.5)^2))-1.0/12.0)<0.01;
        float saved <- ranr_uniform(101,23,7); loop k from: 1 to: 500 { float discarded <- ranr_uniform(555,k,8); }
        assert saved=ranr_uniform(101,23,7);
        write "RANR_SCIENTIFIC_PASS";
    }
}
experiment "ranr_scientific" type:gui { float seed <- 91001.0; }
