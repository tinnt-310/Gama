model ranr_mobility_tests
import "../main.gaml"

global {
    int cars <- 1; int privates <- 0; int taxis <- 0;
    float step <- 60.0; float initial_hour <- 12.0;
    float ranr_car_speed <- 1.0;
    bool ranr_development <- true; bool ranr_gui_preview <- false;
    bool ranr_render <- false; bool have_rush <- false;
    int ranr_samples <- 1;
    string ranr_run_id <- "mobility_fixture";
    string ranr_output <- "../../outputs/gama_ranr/mobility_fixture";
    string fixture_branch <- "return";
    vehicle driving_probe;
    path original_path;
    point last_location;
    float last_metres <- 0.0;

    action ranr_fleet_initialized {
        driving_probe <- car[0];
        intersection origin <- ranr_stations[0].closest_intersection;
        list<building> destinations <- list(building) where (each.closest_intersection.location distance_to origin.location>2000.0 and each.closest_intersection.location distance_to origin.location<4000.0);
        assert !empty(destinations);
        building fixture_building <- destinations[0];
        ask driving_probe {
            do unregister; final_target <- nil; location <- origin.location;
            home <- building closest_to origin;
            work_place <- home; target <- fixture_building;
            is_work_car <- true; is_entertainment_car <- false;
            day_start <- 100.0; day_end <- 200.0;
            day_start_time <- false; day_end_time <- false;
            has_lunch <- true; temp_target <- nil; wait_until <- -1.0;
            do compute_path graph:road_network source:origin target:fixture_building.closest_intersection;
        }
        assert driving_probe.final_target!=nil;
        last_location <- driving_probe.location;
    }
    reflex trigger_schedule when:cycle=2 {
        assert driving_probe.final_target!=nil;
        original_path <- driving_probe.current_path;
        if fixture_branch="morning" { driving_probe.day_start_time <- true; driving_probe.target <- nil; }
        if fixture_branch="lunch" {
            // The keyed draw is repeatable; choose a fixture ID that accepts lunch.
            loop while:!driving_probe.mobility_flip(0.5,1) { driving_probe.mobility_id <- driving_probe.mobility_id+1; }
            driving_probe.has_lunch <- false;
        }
        if fixture_branch="return" { driving_probe.wait_until <- simulation_hour; }
    }
    reflex verify_trip_continues when:cycle=3 {
        assert driving_probe.current_path=original_path;
        assert driving_probe.final_target!=nil;
    }
    reflex verify_recorded_movement {
        assert driving_probe.location distance_to last_location<=driving_probe.ranr_lifetime_metres-last_metres+1e-3;
        last_location <- driving_probe.location; last_metres <- driving_probe.ranr_lifetime_metres;
        if cycle=7 { write "RANR_MOBILITY_RETARGET_PASS "+fixture_branch; }
    }
}
experiment "ranr_mobility" type:gui parent:"Run me" {
    parameter "Schedule branch" var:fixture_branch among:["morning","lunch","return"];
}
