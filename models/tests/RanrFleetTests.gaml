model ranr_unified_fleet_tests
import "../main.gaml"

global {
    int cars <- 10;
    int privates <- 10;
    int taxis <- 10;
    float initial_hour <- 0.0;
    bool ranr_development <- true;
    bool ranr_gui_preview <- false;
    string ranr_run_id <- "fleet_fixture";
    string ranr_output <- "../../outputs/gama_ranr/unified_fleet_fixture";
    float ranr_warmup <- 0.0;
    float ranr_measure <- 1.0;
    float ranr_deadline <- 2.0;
    int ranr_samples <- 4;
    float ranr_true_defer <- 1.0;
    elecar probe;
    elecar flat_battery;
    vehicle visitor;
    reflex fixture_setup when: cycle=0 {
        assert length(ranr_city_vehicles)=30 and length(ranr_gateways)=4;
        assert length(private_ev)=10 and length(taxi_ev)=10;
        probe <- private_ev[0]; flat_battery <- private_ev[1];
        probe.battery_level <- 30.0;
        assert ranr_eligibility(probe)="soc_not_low";
        probe.battery_level <- 29.0;
        assert ranr_eligibility(probe)="activated";
        probe.needs_charging <- true; assert ranr_eligibility(probe)="busy"; probe.needs_charging <- false;
        flat_battery.battery_level <- 0.0;
        ranr_opportunities <- [];
        do ranr_plan_opportunity(probe.mobility_id,"private",0.0,"burst");
        do ranr_plan_opportunity(probe.mobility_id,"private",0.0,"burst");
        do ranr_plan_opportunity(-1,"private",0.0,"burst");
        ranr_opportunity_cursor <- 0;
    }
    reflex fixture_after_request when: cycle=1 {
        assert length(ranr_city_vehicles)=30 and !dead(probe) and !dead(flat_battery);
        assert flat_battery.ranr_stranded;
        assert ranr_activated_count=1 and ranr_burst_shortfall=2;
        assert length(ranr_outcomes)=1 and probe.requested_energy=30.6;
        assert abs(probe.battery_level-29.0)<1e-9;
        assert ranr_opportunity_count=3;
        do ranr_spawn_inbound(["id"::900001,"kind"::"car","gateway"::0,"depart"::0.0]);
        visitor <- ranr_vehicle_by_id[900001];
        assert visitor!=nil and visitor.ranr_inbound;
        assert visitor.location distance_to ranr_gateways[0].location<2.0;
        assert visitor.final_target!=nil;
    }
    reflex fixture_after_end when: cycle=2 {
        assert !dead(visitor); // End time alone must not delete a moving visitor.
        assert length(ranr_city_vehicles where (!each.ranr_inbound))=30;
        ask visitor { do unregister; final_target <- nil; }
        visitor.location <- ranr_gateways[0].location; visitor.ranr_exiting <- true;
    }
    reflex fixture_exit when: cycle=3 {
        assert dead(visitor) and ranr_inbound_exited=1;
        assert length(ranr_city_vehicles)=30;
        if ranr_method="No-P2P" { assert ranr_message_count=0 and ranr_received_count=0; }
        if ranr_method="No-Prediction" { assert ranr_future_calls=0; }
        save list(ranr_outcomes.values) to:ranr_output+"/fixture_outcomes.json" format:"json";
        save ["method"::ranr_method,"opportunities"::ranr_opportunity_count,"activated"::ranr_activated_count,
            "burst_shortfall"::ranr_burst_shortfall,"messages"::ranr_message_count,"future_calls"::ranr_future_calls,
            "persistent"::length(ranr_city_vehicles),"inbound_exited"::ranr_inbound_exited]
            to:ranr_output+"/fixture_diagnostics.json" format:"json";
        do ranr_flush;
        write "RANR_UNIFIED_FLEET_PASS "+ranr_method;
    }
}
experiment "unified_fleet_test" type:gui parent:"Run me";
