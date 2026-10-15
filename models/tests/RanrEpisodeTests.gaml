model ranr_episode_tests
import "../main.gaml"
global {
    float step <- 60.0;
    bool fixture_drive <- false;
    int cars <- 2; int privates <- 3; int taxis <- 2;
    bool ranr_development <- true; bool ranr_gui_preview <- false; bool have_rush <- false;
    float ranr_private_frequency <- 0.0; float ranr_taxi_frequency <- 0.0;
    float ranr_warmup <- 0.0; float ranr_measure <- 2.0; float ranr_deadline <- 20.0;
    float ranr_true_compliance <- 1.0; float ranr_true_defer <- 0.0;
    float ranr_delay <- 1000000.0; int ranr_samples <- 4;
    string ranr_run_id <- "episode_fixture";
    string ranr_output <- "../../outputs/gama_ranr/episode_fixture";
    reflex setup_probe when:cycle=0 {
        // Explicit fixture intervention; never used by production demand generation.
        list<float> capacities <- ranr_stations collect max(list<float>(each.ranr_local_snapshot["powers"]));
        int best <- capacities index_of max(capacities);
        assert capacities[best]>=120.0;
        elecar ev <- private_ev[0];
        ask ev { do unregister; final_target <- nil; battery_level <- 29.0; ranr_max_kw <- 120.0; location <- ranr_stations[best].closest_intersection.location; }
        if fixture_drive {
            bool located <- false;
            loop node over:(access_intersections sort_by (each.location distance_to ranr_stations[best].closest_intersection.location)) {
                if node.location distance_to ranr_stations[best].closest_intersection.location<10.0 { continue; }
                path route <- path_between(road_network,node,ranr_stations[best].closest_intersection);
                if route!=nil and !empty(route.edges) and sum(route.edges collect road(each).shape.perimeter)<500.0 {
                    ev.location <- node.location; located <- true; break;
                }
            }
            assert located;
        }
        loop sid from:0 to:length(ranr_public_priors)-1 {
            if sid!=best { ranr_public_priors[sid]["connectors"] <- ["incompatible"]; ranr_stations[sid].ranr_connectors <- ["incompatible"]; }
        }
        do ranr_plan_opportunity(ev.mobility_id,"private",0.0,"scheduled");
        save ranr_opportunities to:ranr_output+"/opportunities.json" format:"json";
    }
    reflex verify_arrival when:fixture_drive and cycle=179 {
        assert private_ev[0].session_state="charging";
        assert private_ev[0].delivered_energy>0.0 and private_ev[0].ranr_lifetime_metres>0.0;
        assert length(session_events where (each["event"]="arrival"))=1;
        write "RANR_TRAVEL_PASS";
    }
    reflex verify_episode when:ranr_done {
        assert length(ranr_city_vehicles)=7;
        assert length(ranr_outcomes)=1;
        map<string,unknown> outcome <- list<map<string,unknown>>(ranr_outcomes.values)[0];
        assert outcome["status"]="completed";
        assert abs(float(outcome["delivered_kwh"])-30.6)<1e-8;
        if !fixture_drive { assert abs(float(outcome["service_time_min"])-17.0)<1e-7; }
        assert !private_ev[0].needs_charging and !dead(private_ev[0]);
        write "RANR_EPISODE_PASS";
    }
}
experiment "ranr_episode" type:gui parent:"Run me" { parameter "Native driving fixture" var:fixture_drive; }
