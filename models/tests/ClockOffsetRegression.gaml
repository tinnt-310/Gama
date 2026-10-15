model clock_offset_regression
import "../main.gaml"

global {
    int cars <- 0;
    int privates <- 0;
    int taxis <- 0;
    bool have_rush <- false;
    float initial_hour <- 23.99;
    reflex verify_clock {
        if cycle = 0 {
            assert abs(simulation_hour - 23.99) < 1e-9;
            assert day_counter = 1;
            assert session_sequence = 0 and charging_ev_count = 0;
            assert mean_ev_soc = 0.0 and grid_energy_kwh = 0.0;
            // Editing the next-run parameter must not jump the active clock.
            initial_hour <- 6.0;
        }
        if cycle = 40 {
            assert abs(time - 40.0) < 1e-9;
            assert abs(simulation_hour - 23.99 - time / 3600.0) < 1e-9;
            assert day_counter = 2 and day_hour = 24.0;
            assert simulation_hour - day_hour >= 0.0;
            assert session_sequence = 0 and empty(ev_population);
            write "CLOCK_OFFSET_REGRESSION_PASS";
        }
    }
}
experiment "clock_offset" type: gui { float seed <- 42.0; }
