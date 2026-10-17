model ranr_lifecycle_tests
import "../main.gaml"

global {
    int cars <- 0; int privates <- 0; int taxis <- 0;
    bool ranr_development <- true; bool ranr_gui_preview <- false;
    bool ranr_render <- false;
    bool have_rush <- false;
    int ranr_samples <- 1;
    string ranr_run_id <- "lifecycle_fixture";
    string ranr_output <- "../../outputs/gama_ranr/lifecycle_fixture";
    string fixture_change <- "none";
    string fixture_expected <- "";

    reflex fixture_mutate when:cycle=1 {
        switch fixture_change {
            match "case" { ranr_case <- "high"; fixture_expected <- "case"; }
            match "compliance" { ranr_true_compliance <- 0.123; fixture_expected <- "compliance"; }
            match "defer" { ranr_true_defer <- 0.7; fixture_expected <- "defer_probability"; }
            match "trace" { ranr_trace <- !ranr_trace; fixture_expected <- "trace"; }
            match "parameters" { ranr_parameters[0] <- 0.123; fixture_expected <- "parameters"; }
            match "retry" { ranr_energy_retry_minutes <- ranr_energy_retry_minutes+1.0; fixture_expected <- "energy_retry_minutes"; }
            match "collection" { ranr_collection_seed <- 800002; fixture_expected <- "collection_seed"; }
            match "enabled" { ranr_enabled <- false; fixture_expected <- "enabled"; }
            match "display" { ranr_render <- !ranr_render; vehicle_icon_size_px <- 32.0; }
        }
    }
    reflex fixture_abort when:ranr_failed {
        assert fixture_expected!="" and fixture_expected in ranr_error;
        assert ranr_done and ranr_tick_epoch=2;
        assert !file_exists(ranr_output+"/completion.json");
        assert file_exists(ranr_output+"/failure.json");
        write "RANR_CONFIGURATION_GUARD_PASS "+fixture_change;
    }
    reflex fixture_display when:fixture_change="display" and cycle=2 {
        assert !ranr_failed and !ranr_done and ranr_tick_epoch=3;
        write "RANR_DISPLAY_CHANGE_PASS";
    }
    reflex fixture_complete when:ranr_done and !ranr_failed {
        assert fixture_change="none" and time/60.0=4320.0;
        assert day_counter=4;
        do export_completed_days;
        assert day_counter=4; // A second flush must not duplicate the final day.
        write "RANR_LAST_DAY_PASS";
    }
}
experiment "ranr_lifecycle" type:gui parent:"Run me" {
    parameter "Fixture change" var:fixture_change among:["none","case","compliance","defer","trace","parameters","retry","collection","enabled","display"];
}
