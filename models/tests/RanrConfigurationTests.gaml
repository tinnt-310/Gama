model ranr_configuration_tests
import "../main.gaml"
global {
    int cars <- 2; int privates <- 3; int taxis <- 2;
    bool ranr_development <- true; bool ranr_gui_preview <- false; bool ranr_render <- false;
    int ranr_samples <- 1;
    string ranr_run_id <- "configuration_fixture";
    action ranr_fleet_initialized {
        assert length(car)=cars and length(private_ev)=privates and length(taxi_ev)=taxis;
        assert length(ranr_city_vehicles)=cars+privates+taxis;
        assert length(ranr_stations)=11 and sum(ranr_stations collect each.installed_port_count)=125;
        loop sid from:0 to:10 {
            assert "aggregate_kw" in ranr_public_priors[sid].keys;
            assert float(ranr_public_priors[sid]["aggregate_kw"])>=0.0;
        }
        // No-P2P and stale fallback expose public installed capacity, not live peers.
        ranr_method <- "No-P2P";
        map<string,unknown> observed <- ranr_stations[0].ranr_observe(0.0,ranr_public_priors);
        list<map<string,unknown>> snapshots <- observed["snapshots"];
        assert snapshots[1]["source"]="prior";
        assert snapshots[1]["aggregate_kw"]=ranr_public_priors[1]["aggregate_kw"];
        write "RANR_CONFIGURATION_PROPAGATION_PASS "+cars+" "+privates+" "+taxis;
    }
}
experiment "ranr_configuration" type:gui parent:"Run me";
