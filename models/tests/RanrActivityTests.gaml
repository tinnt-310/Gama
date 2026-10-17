model ranr_activity_tests
import "../main.gaml"
global {
    int cars <- 3000; int privates <- 1000; int taxis <- 700;
    bool ranr_development <- true; bool ranr_gui_preview <- false; bool ranr_render <- false;
    bool ranr_calibrating <- true; bool have_rush <- true;
    float step <- 60.0; int ranr_samples <- 1;
    string ranr_run_id <- "activity_fixture";
    string ranr_output <- "../../outputs/gama_ranr/activity_fixture";
    map<int,list<float>> stored_traits <- [];
    action ranr_fleet_initialized {
        assert length(ranr_city_vehicles)=4700 and length(ranr_stations)=11;
        assert sum(ranr_stations collect each.installed_port_count)=125;
        loop ev over:ev_population {
            stored_traits[ev.mobility_id] <- [ev.soc_request_threshold,ev.soc_preferred_target];
            map<string,unknown> again <- ranr_ev_traits(ev.mobility_id,ev.ranr_vehicle_kind);
            assert ev.soc_request_threshold=float(again["soc_request_threshold"]) and ev.soc_preferred_target=float(again["soc_preferred_target"]);
            assert !empty(ev.activity_schedule);
        }
        loop kind over:["private","taxi"] {
            list<elecar> group <- ev_population where (each.ranr_vehicle_kind=kind);
            list<float> probabilities <- list<float>(ranr_environment[kind+"_threshold_probabilities"]);
            loop bin from:0 to:5 {
                float fraction <- float(length(group where (each.soc_request_threshold>=10.0+bin*10.0 and each.soc_request_threshold<20.0+bin*10.0)))/length(group);
                assert abs(fraction-probabilities[bin])<0.065;
            }
            list<float> targets <- list<float>(ranr_environment[kind+"_target_soc_values"]);
            list<float> expected <- list<float>(ranr_environment[kind+"_target_probabilities"]);
            loop j from:0 to:length(targets)-1 {
                float fraction <- float(length(group where (each.soc_preferred_target=targets[j])))/length(group);
                assert abs(fraction-expected[j])<0.065;
            }
        }
        assert mean(taxi_ev collect each.soc_request_threshold)>mean(private_ev collect each.soc_request_threshold);
        assert !empty(ranr_activity_plan where (each["kind"]="passenger"));
        assert !empty(ranr_activity_plan where (each["kind"]="break"));
        assert !empty(ranr_activity_plan where (each["kind"]="work"));
    }
    reflex check_persistence when:cycle=1 {
        loop ev over:ev_population {
            assert [ev.soc_request_threshold,ev.soc_preferred_target]=stored_traits[ev.mobility_id];
        }
        assert !file_exists(ranr_output+"/opportunities.json");
        assert !file_exists(ranr_output+"/energy_opportunities.json");
        write "RANR_ACTIVITY_DISTRIBUTIONS_PASS";
    }
}
experiment "ranr_activity" type:gui parent:"Run me";
