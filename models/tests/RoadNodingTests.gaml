model road_noding_tests
import "../main.gaml"

global {
    geometry shape <- rectangle(100,100);
    bool coordination_enabled <- false;
    init {
        create road with: [shape::polyline([{10,10},{15,10},{20,10}])];
        create road with: [shape::polyline([{15,10},{15,15}])];
        create road with: [shape::polyline([{17,8},{17,12}])];
        source_road_length <- sum(list(road) collect each.shape.perimeter);
        do node_shared_road_vertices;
        assert length(road) = 4;
        assert abs(sum(list(road) collect each.shape.perimeter)-19.0) < 1e-9;
        graph g <- as_edge_graph(road);
        assert length(connected_components_of(g)) = 2;
        assert length(g.vertices) = 6;
        write "ROAD_NODING_TESTS_PASS";
    }
}
experiment "noding" type: gui { float seed <- 42.0; }
