model elapsed_clock_regression
import "../Mobility.gaml"

global {
    float step <- 60.0;
    geometry shape <- rectangle(100,100);
    init {
        assert format_elapsed_hm(0.0) = "00:00";
        assert format_elapsed_hm(59.0) = "00:00";
        assert format_elapsed_hm(60.0) = "00:01";
        assert format_elapsed_hm(3599.0) = "00:59";
        assert format_elapsed_hm(3600.0) = "01:00";
        assert format_elapsed_hm(20160.0) = "05:36";
        assert format_elapsed_hm(86400.0) = "24:00";
        assert format_elapsed_hm(359940.0) = "99:59";
        assert format_elapsed_hm(360000.0) = "100:00";
        assert format_elapsed_hm(604800.0) = "168:00";
        assert format_elapsed_hm(3600000.0) = "1000:00";
    }
    reflex verify_running_clock when: cycle = 1 {
        assert time = 60.0;
        assert elapsed_clock_hm = "00:01";
        assert simulation_hour = 1.0 / 60.0;
        write "ELAPSED_CLOCK_HM_PASS";
    }
}
experiment "elapsed_clock" type: gui { float seed <- 42.0; }
