model ranr_objective_tests
import "../ranr/Evaluation.gaml"
global {
    geometry shape <- rectangle(100,100);
    float step <- 60.0;
    map<string,unknown> objective_fixture(string identity,float issued,float finished,bool arrived,string terminal) {
        map<string,unknown> row <- ranr_record(["intent_id"::identity,"issued_min"::issued,"at"::issued,"deadline"::(issued+360.0),"finished_min"::finished,
            "status"::terminal,"requested_kwh"::10.0,"delivered_kwh"::(terminal="completed" ? 10.0 : 0.0),"energy_complete"::(terminal="completed"),
            "completion_time_min"::(terminal="completed" ? finished-issued : nil),"on_time"::(terminal="completed" and finished<=issued+360.0),
            "right_censored"::(terminal="unresolved"),"queue_eligible"::arrived,"elapsed_min"::(finished-issued),
            "travel_min"::0.0,"waiting_min"::(arrived ? 20.0 : 0.0),"charging_min"::0.0,"deferred_min"::0.0,"retry_delay_min"::0.0,
            "other_elapsed_min"::(finished-issued-(arrived ? 20.0 : 0.0))]);
        return row;
    }
    map<string,unknown> objective_input(list<map<string,unknown>> rows) {
        return ranr_record(["intents"::rows,"results"::rows,"planned_ev_days"::10.0,"observation_end"::4320.0,"queue_pressure"::0.25,"stranded_count"::0,"mobility_unserved_count"::0]);
    }
    init {
        ranr_warmup <- 360.0; ranr_measure <- 3600.0;
        map<string,unknown> complete <- objective_fixture("i1",400.0,460.0,true,"completed");
        map<string,unknown> late <- objective_fixture("i2",400.0,800.0,true,"completed");
        map<string,unknown> open <- objective_fixture("i3",400.0,4320.0,false,"unresolved");
        map<string,unknown> score <- ranr_score(objective_input([complete,late,open]));
        assert bool(score["fitness_valid"]);
        assert score["not_on_time_count"]=2 and score["waiting_sample_count"]=2;
        assert abs(float(score["p95_wait_min"])-20.0)<1e-8;
        assert abs(float(score["mean_completion_min"])-230.0)<1e-8;
        assert list<float>(score["fitness_vector"])[2]=0.2;
        map<string,unknown> duplicated <- objective_input([complete,complete]);
        score <- ranr_score(duplicated); assert !bool(score["fitness_valid"]) and score["fitness_vector"]=nil;
        map<string,unknown> omitted <- objective_input([complete,open]); omitted["results"] <- [complete];
        score <- ranr_score(omitted); assert !bool(score["fitness_valid"]);
        map<string,unknown> short <- objective_input([complete]); short["observation_end"] <- 4000.0;
        score <- ranr_score(short); assert !bool(score["fitness_valid"]);
        map<string,unknown> empty_shadow <- ranr_shadow([60.0],[0.0],[]);
        assert empty(list<float>(empty_shadow["waits"])) and float(empty_shadow["total"])=0.0;
        map<string,unknown> cancelled <- ranr_shadow([60.0],[0.0],[["at"::0.0,"energy"::54.0,"max_kw"::60.0,"service_until"::1.0],["at"::0.0,"energy"::9.0,"max_kw"::60.0]]);
        assert abs(list<float>(cancelled["starts"])[1]-1.0)<1e-8;
        cancelled <- ranr_shadow([60.0],[20.0],[["at"::0.0,"energy"::54.0,"max_kw"::60.0,"service_until"::1.0]]);
        assert abs(list<float>(cancelled["waits"])[0]-1.0)<1e-8;
        list<float> capped <- ranr_allocate_power([60.0,60.0],[30.0,120.0],60.0);
        assert abs(capped[0]-20.0)<1e-9 and abs(capped[1]-40.0)<1e-9;
        map<string,unknown> service <- ranr_service_schedule([60.0,60.0],[["port"::0,"at"::0.0,"energy"::27.0,"max_kw"::120.0],["port"::1,"at"::0.0,"energy"::27.0,"max_kw"::120.0]],60.0,120.0);
        assert bool(service["cleared"]) and abs(float(service["duration"])-60.0)<1e-7;
        service <- ranr_service_schedule([11.0],[["at"::0.0,"energy"::9.9,"max_kw"::120.0]],11.0,120.0);
        assert bool(service["cleared"]) and abs(float(service["duration"])-60.0)<1e-7;
        service <- ranr_service_schedule([0.0],[["at"::0.0,"energy"::10.0,"max_kw"::120.0]],0.0,120.0);
        assert !bool(service["cleared"]) and sum(list<float>(service["delivered"]))=0.0;
        ranr_taper_soc <- [0.0,80.0]; ranr_taper_factors <- [1.0,0.5];
        service <- ranr_service_schedule([60.0],[["at"::0.0,"energy"::12.0,"max_kw"::60.0,"soc"::70.0]],60.0,120.0);
        assert bool(service["cleared"]) and abs(float(service["duration"])-20.0)<1e-7;
        write "RANR_OBJECTIVE_PASS";
    }
}
experiment "ranr_objective" type:gui;
