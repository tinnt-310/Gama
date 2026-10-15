model station_access_tests
import "../main.gaml"

global {
    int cars <- 0;
    int privates <- 0;
    int taxis <- 0;
    bool have_rush <- false;
    bool coordination_enabled <- false;
    reflex verify_access when: cycle = 0 {
        assert length(charging_station) = 11;
        assert abs(sum(list(road) collect each.shape.perimeter)-2.0*source_road_length) < 1e-5;
        list<geometry> original_sites <- shape_file(resources_dir + "temporary_cs.shp").contents;
        loop site_index from: 0 to: 10 {
            charging_station station <- charging_station[site_index];
            assert station.location distance_to original_sites[site_index].location < 1e-6;
            assert station.location distance_to station.closest_intersection.location <= 300.0;
            loop other over: charging_station {
                if station = other { continue; }
                path route <- path_between(road_network,station.closest_intersection,other.closest_intersection);
                assert route != nil and !empty(route.edges);
            }
            create private_ev with: [location::station.closest_intersection.location,battery_level::29.0] {
                ask world { do build_candidates(myself); }
                assert length(candidates) = 11;
                assert first(candidates) = station;
                do die;
            }
        }
        candidate_mode <- "TOP_K";
        create private_ev with: [location::charging_station[0].closest_intersection.location,battery_level::29.0] {
            ask world { do build_candidates(myself); } assert length(candidates) = 3; do die;
        }
        write "STATION_ACCESS_TESTS_PASS";
    }
}
experiment "access" type: gui { float seed <- 42.0; }
