model ranr_unified_fleet_tests
import "../main.gaml"
global {
    float step <- 1.0;
    int cars <- 10; int privates <- 10; int taxis <- 10;
    bool ranr_development <- true; bool ranr_gui_preview <- false; bool ranr_render <- false;
    string ranr_run_id <- "fleet_fixture";
    string ranr_output <- "../../outputs/gama_ranr/unified_fleet_fixture";
    float ranr_warmup <- 0.0; float ranr_measure <- 1.0; float ranr_deadline <- 2.0;
    int ranr_samples <- 1; float ranr_true_defer <- 1.0;
    elecar probe; elecar flat_battery; vehicle visitor;
    action ranr_fleet_initialized {
        ask ev_population { battery_level <- 100.0; activity_schedule <- []; }
        probe <- private_ev[0]; flat_battery <- private_ev[1];
        probe.battery_level <- 29.0; probe.soc_request_threshold <- 30.0;
        flat_battery.battery_level <- 0.0;
    }
    reflex fixture_after_request when:cycle=1 {
        assert length(ranr_city_vehicles)=30 and !dead(probe) and !dead(flat_battery);
        assert flat_battery.ranr_stranded;
        assert length(ranr_intents)=1 and length(ranr_attempts)=1 and length(ranr_outcomes)=1;
        assert probe.charging_intent_id!="" and probe.charging_deferred_reason="voluntary_deferred";
        do ranr_spawn_inbound(["id"::900001,"kind"::"car","gateway"::0,"depart"::0.0]);
        visitor <- ranr_vehicle_by_id[900001];
        assert visitor!=nil and visitor.ranr_inbound and visitor.final_target!=nil;
        assert visitor.location distance_to ranr_gateways[0].location<2.0;
    }
    reflex fixture_after_end when:cycle=2 {
        assert !dead(visitor);
        assert length(ranr_city_vehicles where (!each.ranr_inbound))=30;
        ask visitor { do unregister; final_target <- nil; }
        visitor.location <- ranr_gateways[0].location; visitor.ranr_exiting <- true;
    }
    reflex fixture_exit when:cycle=3 {
        assert dead(visitor) and ranr_inbound_exited=1 and length(ranr_city_vehicles)=30;
        if ranr_method="No-P2P" { assert ranr_message_count=0 and ranr_received_count=0; }
        if ranr_method="No-Prediction" { assert ranr_future_calls=0; }
        do ranr_flush;
        write "RANR_UNIFIED_FLEET_PASS "+ranr_method;
    }
}
experiment "unified_fleet_test" type:gui parent:"Run me";
