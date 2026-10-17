model ranr_episode_tests
import "../main.gaml"
global {
    float step <- 60.0;
    int cars <- 2; int privates <- 3; int taxis <- 2;
    bool ranr_development <- true; bool ranr_gui_preview <- false; bool ranr_render <- false;
    bool have_rush <- false; bool ranr_calibrating <- true;
    float ranr_warmup <- 0.0; float ranr_measure <- 2.0; float ranr_deadline <- 238.0;
    float ranr_true_compliance <- 1.0; float ranr_true_defer <- 0.0;
    int ranr_samples <- 1;
    string ranr_run_id <- "episode_fixture";
    string ranr_output <- "../../outputs/gama_ranr/episode_fixture";
    action ranr_fleet_initialized {
        ask ev_population { battery_level <- 100.0; activity_schedule <- []; }
        elecar ev <- private_ev[0];
        ask ev { do unregister; final_target <- nil; battery_level <- 29.0; soc_request_threshold <- 30.0; soc_preferred_target <- 85.0; location <- ranr_stations[0].closest_intersection.location; }
    }
    reflex verify_episode when:ranr_done {
        assert length(ranr_city_vehicles)=7 and !dead(private_ev[0]);
        assert length(ranr_intents)=1 and length(ranr_intent_outcomes)=1;
        assert list(ranr_intent_outcomes.values)[0]["status"]="completed";
        assert abs(private_ev[0].battery_level-85.0)<1e-7;
        assert empty(ranr_stations where (!empty(each.charging_vehicles) or !empty(each.waiting_queue)));
        assert sum(ranr_stations collect each.installed_port_count)=125;
        write "RANR_EPISODE_PASS";
    }
}
experiment "ranr_episode" type:gui parent:"Run me";
