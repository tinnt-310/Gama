model main

import "ranr/Runtime.gaml"

global {
    bool ranr_enabled <- true;
    float consumption_kwh_km <- float(ranr_environment["consumption_kwh_km"]);
    float charge_efficiency <- float(ranr_environment["charge_efficiency"]);
    string run_prefix <- "";
    string output_directory <- "";



    list<road> open_roads;
    list<intersection> access_intersections <- [];
    float source_road_length <- 0.0;
    map<rgb, string> legends <- [color_car::"Cars", color_road::"Roads", color_lake::"Rivers & Lakes", color_private::"Private EVs"];
    rgb color_car <- #red;
    rgb color_private <- #yellow;
    rgb color_taxi <- #cyan;
    rgb color_road <- rgb(235,115,80);
    rgb color_lake <- rgb(165, 199, 238, 255);
    rgb color_inner_building <- rgb(100, 100, 100);
    rgb color_charging_station <- #orange;


    list <vehicle> entertain_car <- [];
    bool rush <- false;
    bool rush_end <- false;
    list <vehicle> rush_vehi <- [];
    list <vehicle> charge_rush_vehi <- [];
    bool otherhalf <- true;
    int rush_activity_departures <- 0;
    float next_population_export <- 0.0;

    // Initialization
    string csv_file_path <- "../outputs/daily_statistics.csv";
    list <charging_station> all_stations <- [];
    list <int> served_pep <- [];
    string resources_dir <- "../includes/";
    shape_file roads_shape_file <- shape_file(resources_dir + "line.shp");
    shape_file buildings_shape_file <- shape_file(resources_dir + "Middle.shp");
    shape_file add_buildings_shape_file <- shape_file(resources_dir + "final.shp");
    shape_file top_buildings_shape_file <- shape_file(resources_dir + "Part1.shp");
    shape_file bottom_buildings_shape_file <- shape_file(resources_dir + "Part2.shp");

    // The road dataset covers all loaded buildings/stations and establishes one GIS projection.
    geometry shape <- envelope(roads_shape_file);
    int working_car <- int(elecars * 0.3);
    // Caps apply separately to each base species, including surviving old extras.
    int rush_cars <- 0;
    int ev_rush <- 0;
    int working_rush <- 0;
    int rush_taxis <- 0;
    int rush_privates <- ev_rush - rush_taxis;
    int total_rush <- rush_taxis + rush_privates + rush_cars;

    int display_refresh_cycles -> max(1,int(10.0 / step));

    list<vehicle> mobility_population -> (agents of_generic_species vehicle);
    int moving_vehicle_count -> length(mobility_population where (each.final_target != nil));
    int waiting_ev_count -> int(sum(list(charging_station) collect length(each.waiting_queue)));
    int charging_ev_count -> int(sum(list(charging_station) collect length(each.charging_vehicles)));
    int inbound_ev_count -> length(ev_population where (each.session_state="en_route"));
    int completed_session_count -> int(sum(list(charging_station) collect each.served_customer));
    float grid_energy_kwh -> sum(list(charging_station) collect each.power_consumed);
    float mean_ev_soc -> empty(ev_population) ? 0.0 : mean(ev_population collect each.battery_level);
    string activity_status -> charging_ev_count > 0 ? "Charging in progress" :
        (inbound_ev_count > 0 ? "EVs travelling to stations" :
        (waiting_ev_count > 0 ? "EVs waiting for a port" :
        (moving_vehicle_count > 0 ? "Vehicles travelling" :
        (simulation_hour - day_hour < 5.0 ? "Night: scheduled departures 05:00-07:00" : "No active trips or station sessions"))));

    init {
        float gis_started <- machine_time;
        if ranr_enabled {
            if ranr_collect_gui { do ranr_prepare_collection; if !("COLLECTION REGISTERED" in ranr_collection_status) { ranr_error <- ranr_collection_status; do pause; return nil; } }
            // GUI starts with a visible, explicitly labelled preview if no
            // trained model exists. Headless disables this option explicitly.
            if ranr_gui_preview and (ranr_run_id="gui" or "gui_" in ranr_run_id) {
                ranr_render <- true;
                string published <- "../outputs/gama_ranr/models/"+ranr_method+"/parameters.json";
                if ranr_parameter_file="" and !file_exists(published) {
                    ranr_development <- true; ranr_gui_preview_active <- true;
                    // Preserve the original private-car and EV fleet and GUI settings.
                    // Preview never alters fleet, demand, samples or clock time.
                    write "RANR GUI PREVIEW: untrained development weights; not a research evaluation";
                }
            }
            do ranr_load_candidate;
            if !ranr_candidate_loaded { ranr_done <- true; write "RANR_ERROR: "+ranr_error; do pause; return nil; }
            if ranr_run_id="gui" { ranr_run_id <- "gui_"+string(machine_time)+"_"+string(int(seed)); ranr_output <- ranr_output+"/"+ranr_run_id; }
            car_speed <- ranr_car_speed; ele_car_speed <- ranr_ev_speed;
            keyed_driving <- true; file ranr_directory <- new_folder(ranr_output); ranr_output <- ranr_directory.path; run_prefix <- ranr_output+"/population"; output_directory <- ranr_output; csv_file_path <- ranr_output+"/daily_statistics.csv";  }
        do refresh_population_targets;
        // Load roads
        write "Simulation Start";
        create road from: roads_shape_file;
        source_road_length <- sum(list(road) collect each.shape.perimeter);
        do node_shared_road_vertices;
        loop r over: road {
            create road with: (shape: polyline(reverse(r.shape.points)), name: r.name, type: r.type, chargeroad: r.chargeroad);
        }
        loop r over: road {
            if (r.chargeroad){
                write r.name;
            }   }

        string headers <- "Day,Station_Name,Cumulative_Mean_Service_Min,Cumulative_Mean_Wait_Min,Cumulative_Travel_M,Cumulative_Grid_KWh\n";
        save headers to: csv_file_path format: "text";

        create building from: shape_file(buildings_shape_file);
        create building from: shape_file(add_buildings_shape_file);
        create building from: shape_file(top_buildings_shape_file);
        create building from: shape_file(bottom_buildings_shape_file);

        ask road {
            agent ag <- building closest_to self;
            float dist <- ag = nil ? 8.0 : max(min(ag distance_to self - 5.0, 8.0), 2.0);
            if (!chargeroad){
                num_lanes <- int(dist / lane_width);}

            capacity <- 1 + (num_lanes * shape.perimeter / 3);
        }

        loop b over: building {
            b.color_outer_building <- b.build_type = 1 ? rgb(90,145,225) : (b.build_type = 2 ? rgb(95,175,115) : rgb(175,110,205));
        }

        open_roads <- list(road);
        do create_all_station_list;
        do update_road(0);
        write "intersection " + length(intersection);

        loop b over: building{
            if (b.build_type = 1){
                buildings_type_1 << b;
            }
            else if (b.build_type = 2){
                buildings_type_2 << b;
            }
            else {
                buildings_type_3 << b;
            }
        }

        create car number:cars with:[location::one_of(buildings_type_1).closest_intersection.location];
        do refresh_population_targets;
        create taxi_ev number:taxis with:[all_stations::all_stations,location::one_of(buildings_type_1).closest_intersection.location];
        create private_ev number:privates with:[all_stations::all_stations,location::one_of(buildings_type_1).closest_intersection.location];
        ask agents of_generic_species vehicle { location <- (intersection closest_to self).location; }

        loop c over: car {
            c.is_entertainment_car <- flip(0.3) ? true : false;
            if c.is_entertainment_car = false {
                c.is_work_car <- true;
            }
        }

        ranr_gis_ms <- machine_time-gis_started;
        loop c over: private_ev {
            c.is_entertainment_car <- flip(0.3) ? true : false;
            if c.is_entertainment_car = false {
                c.is_work_car <- true;
            }
        }

    }

    reflex export_daily_statistics when: !ranr_done and simulation_hour >= (day_counter * 24) {
        // Prepare data for all stations
        loop station over: all_stations {
            // Get statistics
            float avg_waiting_time <- station.get_average_waiting_time();
            float vehicles_charging_time <- station.get_average_charging_time();
            float vehicles_distance_travel <- station.total_distance_travel;
            float station_power_consumed <- station.power_consumed;
            string station_name <- station.name;

            // Create CSV line
            string line <- ""+day_counter+","+station_name+","+vehicles_charging_time+","+avg_waiting_time+","+vehicles_distance_travel+","+station_power_consumed+"\n";

            // Append to CSV file
            save line to: csv_file_path format: 'text' rewrite: false;

        }
        // Increment day counter
        day_counter <- day_counter + 1;
        half <- true;
        otherhalf <- true;
        rush <- false;
        rush_end <- false;
        // Active sessions persist across midnight.
    }

    action refresh_population_targets {
        assert elecars >= 0 and cars >= 0;
        assert taxis>=0 and privates>=0;
        working_car <- int(elecars * 0.3);
        assert rush_extra_percent >= 0.0 and rush_extra_percent <= 100.0;
        rush_cars <- int(floor(cars * rush_extra_percent / 100.0));
        rush_taxis <- int(floor(taxis * rush_extra_percent / 100.0));
        rush_privates <- int(floor(privates * rush_extra_percent / 100.0));
        ev_rush <- rush_taxis + rush_privates;
        working_rush <- 0;
        total_rush <- rush_cars + ev_rush;
    }


    action create_all_station_list {
        create charging_station from: shape_file(resources_dir + "temporary_cs.shp") with: [
        name::string(read("temp_name")),
        Address::string(read("Name")),
        port_250::int(read("Port_250KW")),
        port_180::int(read("Port_180KW")),
        port_150::int(read("Port_150KW")),
        port_60::int(read("Port_60KW")),
        port_30::int(read("Port_30KW")),
        port_11::int(read("Port_11KW"))
        ];
        loop cs over: list(charging_station) {
            if (cs.port_250>0 or cs.port_180>0 or cs.port_150>0 or cs.port_60 >0 or cs.port_30 >0 or cs.port_11 >0)
            {add cs to: all_stations;}
        }
    }

    reflex export_population when: !ranr_done and time >= next_population_export {
        string population_path <- run_prefix + "_population.csv";
        if !file_exists(population_path) {
            save "time_min,configured_cars,configured_evs,total_cars,total_evs,moving_vehicles,rush_enabled,rush_departures,extra_rush_vehicles,extra_cars,extra_taxis,extra_privates,rush_extra_percent,private_evs,electric_taxis\n"
                to: population_path format: "text";
        }
        string population_row <- string(time/60.0) + "," + cars + "," + elecars + "," +
            (length(car)) + "," + length(ev_population) + "," +
            moving_vehicle_count + "," + have_rush + "," + rush_activity_departures + "," +
            length(mobility_population where each.ranr_inbound) + "," +
            length(list(car) where each.ranr_inbound) + "," + length(list(taxi_ev) where each.ranr_inbound) + "," + length(list(private_ev) where each.ranr_inbound) + "," + rush_extra_percent + "," +
            (length(private_ev)) + "," + (length(taxi_ev)) + "\n";
        save population_row to: population_path format: "text" rewrite: false;
        next_population_export <- time + 60.0;
    }






    action node_shared_road_vertices {
        // Existing shared vertices are junctions even inside an OSM polyline.
        // Do not join geometric crossings without a shared source vertex.
        map<point,int> occurrences <- [];
        list<road> source_roads <- copy(list(road));
        loop r over: source_roads {
            loop pt over: remove_duplicates(r.shape.points) {
                occurrences[pt] <- (pt in occurrences.keys ? occurrences[pt] : 0) + 1;
            }
        }
        loop r over: source_roads {
            list<point> pts <- r.shape.points;
            bool needs_split <- false;
            if length(pts) > 2 {
                loop vertex_index from: 1 to: length(pts) - 2 {
                    if occurrences[pts[vertex_index]] > 1 { needs_split <- true; }
                }
            }
            if !needs_split { continue; }
            list<point> segment <- [pts[0]];
            loop vertex_index from: 1 to: length(pts) - 1 {
                segment << pts[vertex_index];
                if vertex_index = length(pts) - 1 or occurrences[pts[vertex_index]] > 1 {
                    create road with: [shape::polyline(segment),type::r.type,chargeroad::r.chargeroad];
                    segment <- [pts[vertex_index]];
                }
            }
            ask r { do die; }
        }
        assert abs(sum(list(road) collect each.shape.perimeter) - source_road_length) < 1e-5;
    }

    action update_road (int scenario) {
        ask building {
            closest_intersection <- nil;
        }

        ask charging_station {
            closest_intersection <- nil;
        }

        ask intersection {
            do die;
        }

        graph g <- as_edge_graph(open_roads);
        loop pt over: g.vertices {
            create intersection with: (shape: pt);
        }

        ask road {
            vehicle_ordering <- nil;
        }

        ask road {
            if (chargeroad){
                capacity <- 10000.0;
                num_lanes <- 10000;

            }
        }
        //build the graph from the roads and intersections
        road_network <- as_driving_graph(open_roads, intersection) with_shortest_path_algorithm "Dijkstra";
        // Attach sites to the public connected network, not isolated parking paths.
        // Their GIS shapes/locations are unchanged; this is the road access node.
        access_intersections <- list(connected_components_of(road_network) with_max_of length(each));
        assert !empty(access_intersections);
        ask building { closest_intersection <- access_intersections closest_to self; }
        ask charging_station {
            closest_intersection <- access_intersections closest_to self;
            assert location distance_to closest_intersection.location <= 300.0;
        }
    }
}

experiment "Run me" type: gui{
    parameter "Auto GUI preview when no trained model (restart required)" category:"RANR" var:ranr_gui_preview <- true;
    parameter "Method (restart required)" category:"RANR" var:ranr_method among:["RANR-AW","No-P2P","No-Prediction","Fixed-Weights"];
    parameter "Scenario (restart required)" category:"RANR" var:ranr_case among:["normal","high","burst","low_compliance","delayed","combined"];
    parameter "GAMA trained parameter file" category:"RANR" var:ranr_parameter_file;
    parameter "Train calibration file" category:"RANR" var:ranr_calibration_file;
    parameter "Development mode (untrained)" category:"RANR" var:ranr_development;
    parameter "Run ID" category:"RANR" var:ranr_run_id;
    parameter "Output directory" category:"RANR" var:ranr_output;
    parameter "Warmup minutes" category:"RANR" var:ranr_warmup;
    parameter "Measurement minutes" category:"RANR" var:ranr_measure;
    parameter "Deadline minutes" category:"RANR" var:ranr_deadline;
    parameter "EV nominal speed (km/h)" category:"RANR" var:ranr_ev_speed;
    parameter "Background nominal speed (km/h)" category:"RANR" var:ranr_car_speed;
    parameter "Monte Carlo samples" category:"RANR" var:ranr_samples;
    parameter "Private EV opportunities/day" category:"RANR" var:ranr_private_frequency min:0.0;
    parameter "Taxi opportunities/day" category:"RANR" var:ranr_taxi_frequency min:0.0;
    parameter "Public charging SOC threshold (%)" category:"RANR" var:ranr_soc_threshold min:0.0 max:100.0;
    parameter "True compliance (environment only)" category:"RANR" var:ranr_true_compliance;
    parameter "Outside/deferred probability" category:"RANR" var:ranr_true_defer;
    parameter "Mean P2P delay (minutes)" category:"RANR" var:ranr_delay;
    parameter "Packet loss" category:"RANR" var:ranr_loss;
    parameter "Burst requests" category:"RANR" var:ranr_burst_size;
    parameter "Render displays" category:"RANR" var:ranr_render;
    parameter "Record full trace" category:"RANR" var:ranr_trace;
    parameter "Calibration collection" category:"RANR" var:ranr_calibrating;

    parameter "Recommendation temperature (restart required)" category:"Research design" var:ranr_temperature;
    parameter "P2P heartbeat minutes (restart required)" category:"Research design" var:ranr_broadcast_period;
    parameter "Minimum P2P interval minutes (restart required)" category:"Research design" var:ranr_min_send;
    parameter "Duplicate packet probability (restart required)" category:"Research design" var:ranr_duplicate_probability;
    parameter "Partition begin minutes (-1 disabled) (restart required)" category:"Research design" var:ranr_partition_begin;
    parameter "Partition end minutes (-1 disabled) (restart required)" category:"Research design" var:ranr_partition_end;
    parameter "Driver behavior (restart required)" category:"Research design" var:ranr_behavior_case among:["high","moderate","low","contextual","misspecified"];
    parameter "Forecast stabilization (restart required)" category:"Research design" var:ranr_stabilization among:["off","smoothing","smoothing_hysteresis"];
    parameter "Failure coefficient (development) (restart required)" category:"Research design" var:ranr_failure_beta;
    parameter "Unmet energy coefficient (development) (restart required)" category:"Research design" var:ranr_energy_beta;
    parameter "Station event JSON file (restart required)" category:"Research design" var:ranr_station_events_file;
    parameter "Decline probability (restart required)" category:"Research design" var:ranr_true_decline min:0.0 max:1.0;
    parameter "Queue abandonment minutes (-1 disabled)" category:"Research design" var:ranr_abandon_after;
    float seed <- 42.0;
    float maximum_cycle_duration <- 0.0;
    parameter "Target SOC (%)" category: "Energy" var: target_soc min: 1.0 max: 100.0;
    parameter "Start hour (restart required)" category: "Time" var: initial_hour min: 0.0 max: 23.0;
    parameter "Seconds per cycle (1 detailed / 60 fast / 3600 coarse)" category: "Time" var: step <- 1.0 among: [1.0,5.0,10.0,30.0,60.0,3600.0];
    parameter "Vehicle icon size (px)" category: "Display" var: vehicle_icon_size_px min: 16.0 max: 80.0 slider: true;

    parameter "Cars (restart required)" category:"Fleet" var:cars min:0 max:5000;
    parameter "Private EVs (restart required)" category:"Fleet" var:privates min:0 max:5000;
    parameter "Electric taxis (restart required)" category:"Fleet" var:taxis min:0 max:5000;

    parameter "EV consumption (kWh/km)" category: "Energy" var: consumption_kwh_km min: 0.0 max: 1.0;
    parameter "Charging efficiency" category: "Energy" var: charge_efficiency min: 0.01 max: 1.0;
    parameter "Rush Activity" category: "Bool" var: have_rush;
    parameter "Extra vehicles per type during rush (%)" category: "Bool" var: rush_extra_percent min: 0.0 max: 30.0;

    output synchronized: ranr_render   {
        layout 1 consoles: false controls: true navigator: false editors: false toolbars: false;
        monitor "Base fleet total" value:cars+privates+taxis;
        monitor "Base opportunities/min (derived)" value:(privates*ranr_private_frequency+taxis*ranr_taxi_frequency)/1440.0;
        monitor "Charging opportunities" value:ranr_opportunity_count;
        monitor "Activated opportunities" value:ranr_activated_count;
        monitor "Inbound vehicles" value:length(mobility_population where each.ranr_inbound);
        monitor "Activity" value: activity_status refresh: ranr_render;
        monitor "RANR error" value: ranr_error refresh: ranr_render;
        monitor "RANR method" value: ranr_method refresh: ranr_render;
        monitor "RANR completed outcomes" value: length(ranr_outcomes) refresh: ranr_render;
        monitor "RANR P2P messages" value: ranr_message_count refresh: ranr_render;
        monitor "RANR parameter status" value: ranr_gui_preview_active ? "GUI PREVIEW / UNTRAINED" : (ranr_development ? "DEVELOPMENT / untrained" : ranr_parameter_file) refresh: ranr_render;
        monitor "Station logical messages" value: ranr_message_count refresh: ranr_render;
        monitor "Results directory" value: output_directory refresh: ranr_render;
        monitor "Elapsed simulation (min)" value: time / 60.0 refresh: ranr_render;
        monitor "Elapsed simulation (hours)" value: time / 3600.0 refresh: ranr_render;
        monitor "Elapsed simulation (hours:minutes)" value: elapsed_clock_hm refresh: ranr_render;
        monitor "Seconds per cycle" value: step refresh: ranr_render;
        monitor "Day / hour" value: "Day " + day_counter + " / " + (simulation_hour - day_hour) refresh: ranr_render;
        monitor "Moving vehicles" value: moving_vehicle_count refresh: ranr_render;
        monitor "Private cars" value:length(car) refresh:ranr_render;
        monitor "Total conventional vehicles" value: length(mobility_population)-length(ev_population) refresh: ranr_render;
        monitor "Total EVs" value: length(ev_population) refresh: ranr_render;
        monitor "Private EVs" value:length(private_ev) refresh:ranr_render;
        monitor "Electric taxis" value:length(taxi_ev) refresh:ranr_render;
        monitor "Rush departures (existing vehicles)" value: rush_activity_departures refresh: ranr_render;
        monitor "EV mean SOC (%)" value: mean_ev_soc refresh: ranr_render;
        monitor "Charging requests (cumulative)" value: ranr_total_recommendations refresh: ranr_render;
        monitor "Inbound EVs" value: inbound_ev_count refresh: ranr_render;
        monitor "Waiting EVs" value: waiting_ev_count refresh: ranr_render;
        monitor "Charging EVs" value: charging_ev_count refresh: ranr_render;
        monitor "Completed sessions" value: completed_session_count refresh: ranr_render;
        monitor "Grid energy (kWh)" value: grid_energy_kwh refresh: ranr_render;
        display Computer virtual: false type: 2d toolbar: true background: #white refresh: ranr_render {
            species road {
                draw self.shape color: color_road width: 1;
            }

            species building {
                draw self.shape color: color_outer_building border: color_outer_building;
            }

            species charging_station {
                draw circle(5 #px) color: color_charging_station border: #black;
                draw name color: #black at: location + {70,0} size: 11;
            }

            // Vehicles are drawn last so buildings cannot cover their images.
            species car aspect: icon;
            species private_ev aspect: icon;
            species taxi_ev aspect: icon;

        }

        display "Chart" type: 2d refresh: ranr_render and cycle mod display_refresh_cycles = 0 {
            chart "Completed charging sessions" type: histogram size: {0.5, 0.5} position: {0, 0} y_range: [0,max(1,completed_session_count)] y_tick_unit: 1 {
                datalist charging_station collect (each.name)  value: charging_station collect (each.served_customer);
            }

            chart "Currently charging EVs" type: histogram size: {0.5, 0.5} position: {0.5, 0} y_range: [0,max(1,charging_ev_count)] y_tick_unit: 1 {
                datalist charging_station collect (each.name) value: charging_station collect length(each.charging_vehicles);
            }

            chart "Current waiting queue" type: histogram size: {0.5, 0.5} position: {0, 0.5} y_range: [0,max(1,waiting_ev_count)] y_tick_unit: 1 {
                datalist charging_station collect (each.name) value: charging_station collect length(each.waiting_queue);
            }

            chart "Grid energy (kWh)" type: series size: {0.5, 0.5} position: {0.5, 0.5} x_label: "Cycle (see seconds per cycle)" {
                datalist charging_station collect (each.name)  value: charging_station collect (each.power_consumed);
            }

        }

        display "Inconvenience Parameters" type: 2d refresh: ranr_render and cycle mod display_refresh_cycles = 0 {
            chart "Mean waiting (min)" type: histogram size: {0.5, 0.5} position: {0, 0.5}{
                datalist charging_station collect (each.name)  value: charging_station collect (each.get_average_waiting_time());
            }
            chart "Mean service (min)" type: histogram size: {1.0, 0.5}{
                datalist charging_station collect (each.name)  value: charging_station collect (each.get_average_charging_time());
            }
            chart "Mean travel (m)" type: histogram size: {0.5, 0.5} position: {0.5, 0.5}{
                datalist charging_station collect (each.name)  value: charging_station collect (each.get_total_distance());
            }
        }



    }

}
experiment "Collect training data" type:gui parent:"Run me" {
    parameter "Calibration seed (restart required)" category:"Collection" var:ranr_collection_seed among:[800001,800002,800003];
    parameter "Collection experiment" category:"Collection" var:ranr_collect_gui <- true;
    user_command "Validate and build calibration" {
        ask world { do ranr_build_gui_calibration; }
    }
    output {
        monitor "Calibration status" value:ranr_collection_status;
    }
}

