model dashboard_regression
import "../main.gaml"

global {
    bool dashboard_checked <- false;
    reflex verify_dashboard when: !dashboard_checked and time >= 120.0 {
        assert abs(time - 120.0) < 1e-9;
        assert abs(simulation_hour - schedule_start_hour - time / 3600.0) < 1e-9;
        assert charging_ev_count = 1;
        assert waiting_ev_count = 0 and inbound_ev_count = 0;
        assert completed_session_count = 0;
        assert grid_energy_kwh > 1.0;
        assert mean_ev_soc > 0.0 and mean_ev_soc <= 100.0;
        assert activity_status = "Charging in progress";
        assert session_sequence >= 1;
        assert first(session_events)["time_min"] = 0.0;
        write "DASHBOARD_VALUES " + [schedule_start_hour,time / 60.0,charging_ev_count,completed_session_count,grid_energy_kwh];
        write "DASHBOARD_REGRESSION_PASS";
        dashboard_checked <- true;
    }
}
experiment "dashboard" type: gui {
    float seed <- 42.0;
    parameter "Small GIS scenario" var: smoke_mode;
    parameter "Start hour" var: initial_hour;
    parameter "Seconds per cycle" var: step;
}
