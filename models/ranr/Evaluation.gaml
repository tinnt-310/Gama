model ranr_evaluation
import "Fleet.gaml"

global {
    int ranr_evaluation_schema <- 5;
    map<string,unknown> ranr_invalid_score(string reason) {
        return ranr_record(["version"::ranr_objective_version,"objective_config_hash"::ranr_objective_config_hash,
            "fitness_valid"::false,"fitness_vector"::nil,"operational_objective"::nil,"failure_reason"::reason]);
    }
    // Authoritative native fitness. Python verifies ledgers and ranks these vectors.
    map<string,unknown> ranr_score(map<string,unknown> input) {
        list<map<string,unknown>> all_intents <- input["intents"];
        list<map<string,unknown>> all_results <- input["results"];
        if length(remove_duplicates(all_intents collect string(each["intent_id"])))!=length(all_intents) or
           length(remove_duplicates(all_results collect string(each["intent_id"])))!=length(all_results) { return ranr_invalid_score("duplicate_intent_or_outcome"); }
        list<string> ids <- all_intents collect string(each["intent_id"]);
        if length(all_results)!=length(all_intents) or !empty(all_results where (!(string(each["intent_id"]) in ids))) { return ranr_invalid_score("missing_or_orphan_outcome"); }
        float exposure <- float(input["planned_ev_days"]);
        if !(exposure>0.0 and exposure<1e100) { return ranr_invalid_score("invalid_planned_exposure"); }
        if float(input["observation_end"])+1e-7<ranr_warmup+ranr_measure+360.0 { return ranr_invalid_score("incomplete_drain"); }
        list<map<string,unknown>> measured <- all_results where (float(each["issued_min"])>=ranr_warmup and float(each["issued_min"])<ranr_warmup+ranr_measure);
        loop result over:all_results {
            if !(result["status"] in ["completed","failed","unresolved"]) or float(result["finished_min"])+1e-7<float(result["issued_min"]) or
               abs(float(result["deadline"])-float(result["issued_min"])-360.0)>1e-7 { return ranr_invalid_score("invalid_lifecycle"); }
            if !(float(result["requested_kwh"])>=0.0 and float(result["requested_kwh"])<1e100 and float(result["delivered_kwh"])>=0.0 and
                 float(result["delivered_kwh"])<=float(result["requested_kwh"])+ranr_energy_tolerance) { return ranr_invalid_score("invalid_energy"); }
            float ledger_duration_min <- 0.0;
            loop field_name over:["travel_min","waiting_min","charging_min","deferred_min","retry_delay_min","other_elapsed_min"] {
                float value <- float(result[field_name]);
                if !(value>=0.0 and value<1e100) { return ranr_invalid_score("invalid_duration"); }
                ledger_duration_min <- ledger_duration_min+value;
            }
            if abs(ledger_duration_min-float(result["elapsed_min"]))>1e-7 { return ranr_invalid_score("time_ledger_mismatch"); }
            if result["status"]="completed" and (!bool(result["energy_complete"]) or result["completion_time_min"]=nil) { return ranr_invalid_score("incomplete_energy_labeled_completed"); }
        }
        list<map<string,unknown>> complete <- measured where (each["status"]="completed");
        list<map<string,unknown>> queued <- measured where bool(each["queue_eligible"]);
        list<float> waits <- queued collect float(each["waiting_min"]);
        float time_component <- empty(complete) ? 0.0 : 0.5*mean(complete collect float(each["completion_time_min"]))/360.0;
        float tail_component <- empty(waits) ? 0.0 : 0.3*ranr_quantile(values:waits,probability:0.95)/360.0;
        float pressure <- float(input["queue_pressure"]);
        if !(pressure>=0.0 and pressure<=1.0) { return ranr_invalid_score("invalid_queue_pressure"); }
        float queue_component <- 0.2*pressure;
        int not_on_time <- length(measured where (!bool(each["on_time"])));
        float unmet <- sum(measured collect (bool(each["energy_complete"]) ? 0.0 : max(0.0,float(each["requested_kwh"])-float(each["delivered_kwh"]))));
        float operational <- time_component+tail_component+queue_component;
        map<string,unknown> result <- ranr_record(["version"::ranr_objective_version,"objective_config_hash"::ranr_objective_config_hash,
            "fitness_valid"::true,"failure_reason"::nil,"operational_objective"::operational,
            "time_component"::time_component,"tail_component"::tail_component,"queue_component"::queue_component,
            "planned_ev_days"::exposure,"stranded_count"::input["stranded_count"],"mobility_unserved_count"::input["mobility_unserved_count"],
            "not_on_time_count"::not_on_time,"unmet_kwh"::unmet,"intent_count"::length(measured),
            "completed_count"::length(complete),"on_time_count"::(length(measured)-not_on_time),
            "failed_count"::length(measured where (each["status"]="failed")),"unresolved_count"::length(measured where (each["status"]="unresolved")),
            "waiting_sample_count"::length(waits),"completion_sample_count"::length(complete),
            "waiting_censored_count"::length(queued where bool(each["right_censored"])),
            "mean_completion_min"::(empty(complete) ? nil : mean(complete collect float(each["completion_time_min"]))),
            "p95_wait_min"::(empty(waits) ? nil : ranr_quantile(values:waits,probability:0.95)),
            "mean_wait_min"::(empty(waits) ? nil : mean(waits)),
            "conditional_success_rate"::(empty(measured) ? nil : float(length(complete))/length(measured)),
            "conditional_on_time_rate"::(empty(measured) ? nil : float(length(measured)-not_on_time)/length(measured))]);
        result["fitness_vector"] <- [float(input["stranded_count"])/exposure,float(input["mobility_unserved_count"])/exposure,float(not_on_time)/exposure,unmet/exposure,operational];
        return result;
    }
    // Attempt facts remain distinct from terminal intent outcomes.
    map<string,unknown> ranr_outcome(map<string,unknown> demand,string rid,string status,float at,float energy,float travel,float waiting,float charging) {
        return ranr_record(["schema"::"request-attempt-outcome-5","attempt_id"::rid,"request_id"::rid,"vehicle_id"::demand["vehicle_id"],
            "intent_id"::("intent_id" in demand.keys ? demand["intent_id"] : "fixture"),"kind"::demand["kind"],"key"::demand["key"],"issued_min"::demand["at"],"finished_min"::at,
            "status"::status,"cause"::status,"failure_origin"::"observed_not_causal","replans"::("replans" in demand.keys ? demand["replans"] : 0),
            "requested_kwh"::demand["energy"],"delivered_kwh"::energy,"energy_complete"::(float(demand["energy"])-energy<=ranr_energy_tolerance),
            "travel_min"::travel,"waiting_min"::waiting,"charging_min"::charging,"service_time_min"::(travel+waiting+charging),"elapsed_min"::(at-float(demand["at"])),"measured"::demand["measured"]]);
    }
}
