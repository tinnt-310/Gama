model ranr_objective_tests
import "../ranr/Evaluation.gaml"
global {
    geometry shape <- rectangle(100,100);
    init {
        ranr_deadline <- 100.0; ranr_failure_beta <- 1.0; ranr_energy_beta <- 1.0;
        map<string,unknown> demand <- ranr_record(["at"::0.0,"energy"::10.0,"vehicle_id"::10000,"kind"::"private","key"::1,"measured"::true]);
        map<string,unknown> complete <- ranr_outcome(demand,"r1","completed",40.0,10.0,10.0,10.0,20.0);
        map<string,unknown> partial <- ranr_outcome(demand,"r2","deadline_missed",100.0,5.0,10.0,60.0,30.0);
        map<string,unknown> score <- ranr_score(["results"::[complete,partial],"opportunities"::[["status"::"activated"],["status"::"activated"],["status"::"soc_not_low"],["status"::"soc_not_low"]],"peak"::5,"ports"::125]);
        assert abs(float(score["time_component"])-0.175)<1e-9;
        assert abs(float(score["failure_component"])-0.25)<1e-9;
        assert abs(float(score["energy_component"])-0.25)<1e-9;
        assert abs(float(score["queue_component"])-0.008)<1e-9;
        assert abs(float(score["tail_component"])-0.1725)<1e-9;
        assert abs(float(score["objective"])-0.8555)<1e-9;
        assert float(complete["service_time_min"])=40.0 and float(partial["service_time_min"])=100.0;
        score <- ranr_score(["results"::[],"opportunities"::[["status"::"soc_not_low"]],"peak"::0,"ports"::125]);
        assert float(score["objective"])=0.0 and bool(score["fitness_valid"]);
        score <- ranr_score(["results"::[],"opportunities"::[["status"::"stranded"]],"peak"::0,"ports"::125]);
        assert float(score["failure_component"])=1.0;
        score <- ranr_score(["results"::[],"opportunities"::[],"peak"::0,"ports"::125]);
        assert !bool(score["fitness_valid"]);
        write "RANR_OBJECTIVE_PASS";
    }
}
experiment "ranr_objective" type:gui;
