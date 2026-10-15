model late_smoke_regression
import "../main.gaml"

global {
    bool smoke_mode <- false;
    int cars <- 4;
    int privates <- 3;
    int taxis <- 3;
    bool have_rush <- false;
    float step <- 60.0;
    reflex request_fixture when: cycle = 0 {
        ask first(ev_population) { battery_level <- 29.0; do begin_request; }
    }
    reflex enable_smoke_late when: cycle = 3 { smoke_mode <- true; }
    reflex verify_late_smoke when: cycle = 5 {
        assert !smoke_checked;
        assert length(car) = 4 and length(ev_population) = 6;
        write "LATE_SMOKE_MODE_PASS";
    }
}
experiment "late_smoke" type: gui { float seed <- 42.0; }
