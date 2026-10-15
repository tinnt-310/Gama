model map_regression
import "../main.gaml"

global {
    reflex verify_map when: cycle = 0 {
        write "WORLD_BOUNDS " + shape + " center=" + location + " dimensions=" + shape.width + "," + shape.height;
        write "ROAD_BOUNDS " + envelope(road);
        write "BUILDING_BOUNDS " + envelope(building);
        write "STATION_BOUNDS " + envelope(charging_station);
        assert shape covers envelope(road);
        assert shape covers envelope(building);
        assert shape covers envelope(charging_station);
        assert shape.width <= 1.05 * envelope(road).width;
        assert shape.height <= 1.05 * envelope(road).height;
        write "MAP_REGRESSION_PASS";
    }
}
experiment "map_regression" type: gui {
    float seed <- 42.0;
    parameter "Small GIS scenario" var: smoke_mode;
}
