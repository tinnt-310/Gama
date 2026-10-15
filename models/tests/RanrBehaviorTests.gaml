model ranr_behavior_tests
import "../ranr/Runtime.gaml"
global {
    geometry shape <- rectangle(100,100);
    init {
        ranr_done <- true;
        create private_ev with:[ranr_vehicle_kind::"private",battery_level::10.0,ranr_stranded::true];
        create taxi_ev with:[ranr_vehicle_kind::"taxi",battery_level::10.0,ranr_stranded::true];
        map<string,unknown> request <- ["travel"::[10.0,20.0]];
        list<float> estimated <- ranr_response_mass([10.0,20.0],0,"default");
        ranr_behavior_case <- "moderate"; assert ranr_driver_compliance(private_ev[0],request)=0.8;
        ranr_behavior_case <- "high"; assert ranr_driver_compliance(private_ev[0],request)=0.95;
        ranr_behavior_case <- "low"; assert ranr_driver_compliance(private_ev[0],request)=0.2;
        ranr_behavior_case <- "misspecified";
        assert ranr_driver_compliance(private_ev[0],request)=0.9 and ranr_driver_compliance(taxi_ev[0],request)=0.1;
        assert estimated=ranr_response_mass([10.0,20.0],0,"default");
        ranr_behavior_case <- "contextual";
        assert ranr_driver_compliance(private_ev[0],request)!=ranr_driver_compliance(taxi_ev[0],request);
        ranr_case <- "low_compliance"; ranr_behavior_case <- "high";
        assert ranr_driver_compliance(private_ev[0],request)=0.2;
        write "RANR_BEHAVIOR_PASS";
    }
}
experiment "ranr_behavior" type:gui;
