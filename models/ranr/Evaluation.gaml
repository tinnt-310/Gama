model ranr_evaluation
import "Fleet.gaml"

global {
    int ranr_evaluation_schema <- 3;
    map<string,unknown> ranr_score(map<string,unknown> input) {
        list<map<string,unknown>> results <- list<map<string,unknown>>(input["results"]);
        list<map<string,unknown>> opp_records <- list<map<string,unknown>>(input["opportunities"]);
        int queue_peak <- int(input["peak"]); int port_count <- int(input["ports"]);
        int denominator <- length(opp_records);
        list<float> waits <- results collect float(each["waiting_min"]);
        float service <- sum(results collect float(each["service_time_min"]));
        float requested <- sum(results collect float(each["requested_kwh"]));
        float unmet <- sum(results collect max(0.0,float(each["requested_kwh"])-float(each["delivered_kwh"])));
        map<string,int> categories <- [];
        loop terminal_status over:["no_feasible_station","voluntary_deferred","declined","abandoned","deadline_missed","stranded"] { categories[terminal_status] <- length(results where (each["status"]=terminal_status)); }
        categories["stranded"] <- categories["stranded"]+length(opp_records where (each["status"]="stranded"));
        float time_component <- 0.5*service/(max(1,denominator)*ranr_deadline);
        float tail_component <- empty(waits) ? 0.0 : 0.3*ranr_quantile(waits,0.95)/ranr_deadline;
        float queue_component <- 0.2*queue_peak/max(1,port_count);
        float failure_component <- ranr_failure_beta*sum(categories.values)/max(1,denominator);
        float energy_component <- requested>0.0 ? ranr_energy_beta*unmet/requested : 0.0;
        return ranr_record(["version"::ranr_objective_version,"objective"::(time_component+tail_component+queue_component+failure_component+energy_component),
            "time_component"::time_component,"tail_component"::tail_component,"queue_component"::queue_component,"failure_component"::failure_component,"energy_component"::energy_component,
            "failure_categories"::categories,"failure_beta"::ranr_failure_beta,"energy_beta"::ranr_energy_beta,"opportunity_denominator"::denominator,
            "requested_energy_denominator_kwh"::requested,"unmet_energy_ratio"::(requested>0.0 ? unmet/requested : 0.0),"fitness_valid"::(denominator>0)]);
    }
    map<string,unknown> ranr_outcome(map<string,unknown> demand,string rid,string status,float at,float energy,float travel,float waiting,float charging) {
        float missing <- max(0.0,float(demand["energy"])-energy);
        if status="completed" and missing>1e-8 { status <- "deadline_missed"; }
        return ranr_record(["schema"::"opportunity-outcome-3","request_id"::rid,"vehicle_id"::demand["vehicle_id"],"kind"::demand["kind"],"key"::demand["key"],"issued_min"::demand["at"],"finished_min"::at,
            "status"::status,"cause"::status,"failure_origin"::(status="completed" ? "none" : ("route_energy_feasible" in demand.keys and !bool(demand["route_energy_feasible"]) ? "exogenous_route_energy" : (status in ["voluntary_deferred","declined","abandoned"] ? "driver_decision" : "physical_service_outcome"))),"replans"::("replans" in demand.keys ? demand["replans"] : 0),"attribution"::"observed_terminal_not_causal_claim","requested_kwh"::demand["energy"],"delivered_kwh"::min(energy,float(demand["energy"])),
            "travel_min"::travel,"waiting_min"::waiting,"charging_min"::charging,"service_time_min"::(travel+waiting+charging),"elapsed_min"::max(0.0,at-float(demand["at"])),"measured"::demand["measured"]]);
    }
}
