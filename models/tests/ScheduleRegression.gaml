model schedule_regression
import "../Mobility.gaml"

global {
    float step <- 24 #h;
    geometry shape <- rectangle(1000,1000);
    init {
        create intersection with: [location::{100,100}];
        create building with: [location::{100,100},closest_intersection::intersection[0]];
        buildings_type_1 <- list(building); buildings_type_2 <- list(building); buildings_type_3 <- list(building);
        create vehicle with: [home::building[0],day_start::6.0,day_end::22.0];
    }
    reflex advance_day {
        if cycle = 1 { day_counter <- 2; }
        if cycle = 2 {
            assert vehicle[0].day_start >= 29.0 and vehicle[0].day_start <= 31.0;
            assert vehicle[0].day_end >= 44.0 and vehicle[0].day_end <= 48.0;
            assert vehicle[0].entertain_time1 >= 32.0;
            write "SCHEDULE_REGRESSION_PASS";
        }
    }
}
experiment "schedule" type: gui { float seed <- 42.0; }
