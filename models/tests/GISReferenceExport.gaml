model gis_reference_export
import "../main.gaml"

global {
    int cars <- 0;
    int privates <- 0;
    int taxis <- 0;
    bool have_rush <- false;
    bool coordination_enabled <- false;
    bool isolate_run_outputs <- false;
    string run_prefix <- "../../outputs/ranr/data/gama_reference";
    reflex export_reference when: cycle = 0 {
        string rows <- "origin,destination,distance_m\n";
        loop source over: charging_station {
            loop target over: charging_station {
                float distance <- 0.0;
                if source != target {
                    path route <- path_between(road_network,source.closest_intersection,target.closest_intersection);
                    assert route != nil;
                    distance <- sum(route.edges collect road(each).shape.perimeter);
                }
                rows <- rows+source.name+","+target.name+","+distance+"\n";
            }
        }
        save rows to: "../../outputs/ranr/data/gama_routes.csv" format: "text";
        write "GIS_REFERENCE_EXPORT_PASS";
    }
}
experiment "gis_reference" type: gui { float seed <- 42.0; }
