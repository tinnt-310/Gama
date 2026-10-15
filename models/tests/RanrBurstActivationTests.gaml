model ranr_burst_activation_tests
import "../main.gaml"
global {
    int cars <- 2; int privates <- 150; int taxis <- 50;
    bool ranr_development <- true; bool ranr_gui_preview <- false;
    bool have_rush <- false;
    float ranr_private_frequency <- 0.0; float ranr_taxi_frequency <- 0.0;
    float ranr_true_defer <- 1.0;
    float ranr_warmup <- 0.0; float ranr_measure <- 1.0; float ranr_deadline <- 1.0;
    int ranr_samples <- 1; // Small correctness fixture, not accuracy evidence.
    int fixture_count <- 200;
    string ranr_run_id <- "burst_activation_fixture";
    string ranr_output <- "../../outputs/gama_ranr/burst_activation_fixture";
    reflex prepare_burst when:cycle=0 {
        assert fixture_count in [20,50,100,200];
        ask ev_population { battery_level <- 29.0; }
        ranr_opportunities <- []; do ranr_plan_burst(0.0,fixture_count);
        save ranr_opportunities to:ranr_output+"/opportunities.json" format:"json";
    }
    reflex verify_burst when:cycle=1 {
        assert ranr_activated_count=fixture_count;
        assert length(ranr_outcomes)=fixture_count;
        assert length(ranr_city_vehicles)=202;
        assert length(remove_duplicates(ranr_opportunity_ledger collect int(each["vehicle_id"])))=fixture_count;
        assert length(list<map<string,unknown>>(ranr_outcomes.values) where (each["status"]="voluntary_deferred"))=fixture_count;
        if ranr_method="No-P2P" { assert ranr_message_count=0; }
        if ranr_method="No-Prediction" { assert ranr_future_calls=0; }
        do ranr_flush;
        save ["size"::fixture_count,"activated"::ranr_activated_count,"persistent"::length(ranr_city_vehicles),"recommendations"::ranr_total_recommendations,"messages"::ranr_message_count]
            to:ranr_output+"/burst_activation_diagnostics.json" format:"json";
        write "RANR_BURST_ACTIVATION_PASS "+fixture_count;
    }
}
experiment "ranr_burst_activation" type:gui parent:"Run me" { parameter "Fixture burst size" var:fixture_count among:[20,50,100,200]; }
