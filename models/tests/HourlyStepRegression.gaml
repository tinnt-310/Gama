model hourly_step_regression
import "CoarseStepRegression.gaml"

global {
    float step <- 3600.0 #s;
    // Reuse the curved-route/one-port fixture, now with one-hour ticks.
    reflex verify_coarse_step {
        if cycle = 1 {
            assert abs(time - 3600.0) < 1e-9;
            assert abs(private_ev[0].total_distance - 400.0) < 1e-6;
            assert abs(private_ev[0].battery_level - 78.88) < 1e-6;
            assert private_ev[0].arrival_time = 60.0 and private_ev[0].service_start = 60.0;
            assert charging_station[0].arrived_customer = 1;
        }
        if cycle = 3 {
            assert charging_station[0].served_customer = 1;
            assert charging_station[0].port_60 = 1;
            assert abs(private_ev[0].delivered_energy - 0.6) < 1e-9;
            assert abs(charging_station[0].power_consumed - 2.0 / 3.0) < 1e-9;
            assert abs(private_ev[0].service_finish - (60.0 + 2.0 / 3.0)) < 1e-9;
            assert length(session_events where (each["event"] = "arrival")) = 1;
            assert length(session_events where (each["event"] = "service_completed")) = 1;
        }
        if cycle = 46 {
            assert abs(time - 46.0 * 3600.0) < 1e-9;
            assert abs(simulation_hour - 46.0) < 1e-9;
            write "HOURLY_STEP_REGRESSION_PASS";
        }
    }
}
experiment "hourly_step" type: gui { float seed <- 42.0; }
