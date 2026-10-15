model ranr_burst_tests
import "../main.gaml"
global {
    int cars <- 2; int privates <- 10; int taxis <- 10;
    bool ranr_development <- true; bool ranr_gui_preview <- false;
    float ranr_private_frequency <- 0.0; float ranr_taxi_frequency <- 0.0;
    string ranr_output <- "../../outputs/gama_ranr/burst_fixture";
    string ranr_run_id <- "burst_fixture";
    int ranr_samples <- 4;
    float ranr_measure <- 1.0; float ranr_warmup <- 0.0; float ranr_deadline <- 1.0;
    reflex burst_contract when:cycle=0 {
        loop count over:[20,50,100,200] {
            ranr_opportunities <- []; do ranr_plan_burst(0.0,count);
            assert length(ranr_opportunities)=count;
            list<int> existing <- ranr_opportunities where (int(each["vehicle_id"])>=0) collect int(each["vehicle_id"]);
            assert length(existing)=20 and length(remove_duplicates(existing))=20;
            assert length(ranr_opportunities where (int(each["vehicle_id"])<0))=count-20;
            assert length(ranr_city_vehicles)=22;
        }
        ranr_opportunities <- [];
        write "RANR_BURST_PASS";
    }
}
experiment "ranr_burst" type:gui parent:"Run me";
