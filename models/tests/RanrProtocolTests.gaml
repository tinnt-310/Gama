model ranr_protocol_tests
import "../ranr/Policy.gaml"
global {
    geometry shape <- rectangle(100,100);
    init {
        ranr_parameters <- zero_vector(20); ranr_method <- "No-Prediction"; ranr_samples <- 8;
        create ranr_station_agent number:2 { ranr_sid <- index; }
        map<string,unknown> snapshot <- ranr_record(["sid"::0,"issued"::0.0,"powers"::[60.0],"release_lo"::[10.0],"release_hi"::[20.0],"queue"::[],"source"::"local","operational"::true,"connectors"::["generic-public"]]);
        list<map<string,unknown>> priors <- [ranr_clone_snapshot(snapshot),ranr_clone_snapshot(snapshot)]; priors[1]["sid"] <- 1;
        ranr_station_agent[0].ranr_local_snapshot <- snapshot;
        map<string,unknown> packet <- ranr_record(["sender"::1,"sequence"::2,"issued"::0.0,"expires"::180.0,"snapshot"::ranr_clone_snapshot(priors[1]),"exposure"::[],"resolutions"::[],"rate"::0.1]);
        ask ranr_station_agent[0] { do ranr_receive(packet,1.0); }
        map<string,unknown> changed <- packet["snapshot"]; changed["release_lo"] <- [999.0];
        map<string,unknown> observed <- ranr_station_agent[0].ranr_observe(1.0,priors);
        list<map<string,unknown>> states <- observed["snapshots"];
        assert list<float>(states[1]["release_lo"])=[10.0];
        packet["sequence"] <- 1; ask ranr_station_agent[0] { do ranr_receive(packet,2.0); }
        assert ranr_station_agent[0].ranr_received_sequence[1]=2;
        packet["sequence"] <- 2; ask ranr_station_agent[0] { do ranr_receive(packet,2.0); }
        assert ranr_station_agent[0].ranr_duplicate_packets=2;
        observed <- ranr_station_agent[0].ranr_observe(1000.0,priors); states <- observed["snapshots"];
        assert states[1]["source"]="local"; // Public prior supplied by fixture, not an expired peer.
        map<string,unknown> request <- ranr_record(["key"::123,"token"::"0:123:0","energy"::9.0,"max_kw"::60.0,"travel"::[1.0,2.0],"connector"::"generic-public","context"::"private"]);
        observed <- ranr_station_agent[0].ranr_observe(2.0,priors);
        map<string,unknown> result <- ranr_station_agent[0].ranr_recommend(request,observed);
        map<string,unknown> retry <- ranr_station_agent[0].ranr_recommend(request,observed);
        assert result=retry and length(ranr_station_agent[0].ranr_local_exposure)=1;
        assert length(list(result["weights"]))=5 and abs(sum(list<float>(result["probabilities"]))-1.0)<1e-9;
        ask ranr_station_agent[0] { do ranr_resolve("0:123:0","cancelled",3.0); }
        observed <- ranr_station_agent[0].ranr_observe(3.0,priors);
        assert empty(list(observed["exposure"]));
        // Altering inaccessible behavior truth has no policy effect.
        ranr_station_agent[0].ranr_request_cache <- []; ranr_true_compliance <- 0.0; ranr_true_defer <- 1.0;
        observed <- ranr_station_agent[0].ranr_observe(2.0,priors);
        map<string,unknown> hidden_changed <- ranr_station_agent[0].ranr_recommend(request,observed);
        assert result["probabilities"]=hidden_changed["probabilities"];
        assert ranr_future_calls=0;
        assert abs(ranr_seen_posterior(0.5,2,1.0)-2.0/3.0)<1e-9;
        assert ranr_seen_posterior(0.7,0,2.0)=0.0;
        assert ranr_seen_posterior(0.7,1,0.0)=1.0;
        ranr_method <- "No-P2P"; observed <- ranr_station_agent[0].ranr_observe(2.0,priors); states <- observed["snapshots"];
        assert states[1]["source"]!="peer";
        write "RANR_PROTOCOL_PASS";
    }
}
experiment "ranr_protocol" type:gui;
