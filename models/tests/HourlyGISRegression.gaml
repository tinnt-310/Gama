model hourly_gis_regression
import "../main.gaml"

global {
    reflex verify_hourly_gis when: cycle = 46 {
        assert step = 3600.0;
        assert abs(time / 3600.0 - 46.0) < 1e-9;
        assert day_counter = 2 and day_hour = 24.0;
        assert simulation_hour - day_hour = 22.0;
        assert completed_session_count >= 1 and grid_energy_kwh >= 34.0 - 1e-9;
        assert empty(ev_population where (each.battery_level < 0.0 or each.battery_level > 100.0));
        assert empty(list(charging_station) where (each.port_250 < 0 or each.port_180 < 0 or each.port_150 < 0 or each.port_60 < 0 or each.port_30 < 0 or each.port_11 < 0));
        do export_run;
        write "HOURLY_GIS_VALUES " + [time / 3600.0,completed_session_count,grid_energy_kwh];
        write "HOURLY_GIS_REGRESSION_PASS";
    }
}
experiment "hourly_gis" type: gui {
    float seed <- 42.0;
    parameter "Small GIS scenario" var: smoke_mode;
    parameter "Seconds per cycle" var: step;
}
