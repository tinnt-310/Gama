model ranr_adaptive_feature_review
import "../../models/ranr/Policy.gaml"
global {
    geometry shape <- rectangle(100,100);
    init {
        map<string,unknown> calibration <- json_file("../../../accepted_data_v5/calibration.json").contents;
        assert calibration["observation_version"]="station-observation-5";
        ranr_release_fractions <- calibration["release_fractions"]; ranr_energy_fractions <- calibration["energy_fractions"];
        ranr_arrival_probability <- float(calibration["arrival_probability"]);
        ranr_eta_factors <- calibration["eta_factors"]; ranr_response_prior <- calibration["response_prior"];
        ranr_prior_snapshots <- calibration["prior_snapshots"]; ranr_arrival_prior <- calibration["arrival_prior"];
        do ranr_index_calibration;
        ranr_samples <- 1; ranr_method <- "RANR-AW"; ranr_parameters <- zero_vector(20);
        create ranr_station_agent { ranr_sid <- 0; }
        list<list<float>> states <- [];
        loop mode from:0 to:4 {
            ranr_station_agent[0].ranr_local_requests <- mode=2 ? [99.0,99.1,99.2,99.3,99.4,99.5,99.6,99.7] : [];
            ranr_station_agent[0].ranr_request_cache <- [];
            ranr_station_agent[0].ranr_local_exposure <- [];
            ranr_scenario_cache <- [];
            list<map<string,unknown>> snapshots <- [];
            loop sid from:0 to:10 {
                snapshots << ["sid"::sid,"issued"::(mode=4 ? 85.0 : 100.0),"powers"::[60.0],"aggregate_kw"::60.0,
                    "release_lo"::[0.0],"release_hi"::[0.0],"busy"::[],
                    "queue"::(mode=1 ? [["low"::9.0,"high"::9.0,"max_kw"::60.0,"soc"::30.0]] : []),
                    "source"::"peer","operational"::true,"connectors"::["generic-public"]];
            }
            list<map<string,unknown>> exposure <- [];
            if mode=3 {
                exposure << ["key"::900,"token"::"uncertain","count"::100,"recommended"::0,"sender"::0,
                    "issued"::100.0,"expires"::460.0,"travel"::zero_vector(11) collect 5.0,
                    "energy"::20.0,"max_kw"::60.0,"context"::"private"];
            }
            map<string,unknown> observation <- ["at"::100.0,"snapshots"::snapshots,"exposure"::exposure,
                "watermarks"::zero_vector(11) collect 100.0,"rates"::zero_vector(11)];
            map<string,unknown> request <- ["key"::(100+mode),"issuer"::0,"token"::("feature_"+mode),"context"::"private",
                "energy"::9.0,"energy_by_station"::zero_vector(11) collect 9.0,"max_kw"::60.0,
                "travel"::zero_vector(11) collect 5.0,"connector"::"generic-public"];
            map<string,unknown> recommendation <- ranr_station_agent[0].ranr_recommend(request,observation);
            list<float> state <- recommendation["state"]; states << copy(state);
            assert length(state)=5 and state[0]=1.0 and min(state)>=0.0 and max(state)<=1.0;
            assert length(list<float>(recommendation["probabilities"]))=11 and abs(sum(list<float>(recommendation["probabilities"]))-1.0)<1e-9;
            write "RANR_FEATURE_REVIEW mode="+mode+" state="+state;
        }
        assert states[1][1]>states[0][1];
        assert states[2][2]>states[0][2];
        assert states[3][3]>states[0][3];
        assert states[4][4]>states[0][4];
        write "RANR_ADAPTIVE_FEATURE_REVIEW_PASS calibrated_v5=true load=true intensity=true response_uncertainty=true age=true";
    }
}
experiment "adaptive_feature_review" type:gui;
