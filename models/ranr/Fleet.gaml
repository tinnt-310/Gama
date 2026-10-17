model ranr_persistent_fleet
import "../ChargingService.gaml"

global {
    list<vehicle> ranr_city_vehicles -> agents of_generic_species vehicle;
    list<intersection> ranr_gateways <- [];
    list<building> ranr_central_buildings <- [];
    map<int,vehicle> ranr_vehicle_by_id <- [];
    map<int,intersection> ranr_nodes_by_id <- [];
    list<map<string,unknown>> ranr_inbound_plan <- [];
    map<int,list<map<string,unknown>>> ranr_mobility_plans <- [];
    list<map<string,unknown>> ranr_activity_plan <- [];
    map<string,map<string,unknown>> ranr_intents <- [];
    list<map<string,unknown>> ranr_attempts <- [];
    list<map<string,unknown>> ranr_need_records <- [];
    map<string,map<string,unknown>> ranr_intent_outcomes <- [];
    map<int,float> ranr_station_distance_by_node <- [];
    map<string,map<string,unknown>> ranr_activity_outcomes <- [];
    list<map<string,unknown>> ranr_time_intervals <- [];
    map<int,bool> ranr_stranded_ids <- [];
    float ranr_planned_ev_days <- 0.0;
    map<int,bool> ranr_exposure_ids <- [];
    bool ranr_fleet_ready <- false;
    float ranr_energy_retry_minutes <- float(ranr_environment["energy_retry_minutes"]);
    float ranr_energy_retry_max_minutes <- float(ranr_environment["energy_retry_max_minutes"]);
    float ranr_energy_urgent_soc <- float(ranr_environment["energy_urgent_soc"]);
    int ranr_inbound_cursor <- 0;
    int ranr_inbound_created <- 0;
    int ranr_inbound_exited <- 0;
    int ranr_attempt_sequence <- 0;
    float ranr_next_vehicle_log <- 0.0;
    string ranr_traffic_buffer <- "";
    string ranr_vehicle_buffer <- "";
    string ranr_activity_buffer <- "";
    string ranr_intent_buffer <- "";

    action ranr_prepare_collection {
        assert ranr_collection_seed in [800001,800002,800003];
        map<string,unknown> config <- json_file(ranr_project_prefix+"configs/gama/calibration.json").contents;
        seed <- float(ranr_collection_seed);
        ranr_method <- "RANR-AW"; ranr_case <- "normal";
        ranr_development <- true; ranr_calibrating <- true; ranr_trace <- true;
        ranr_gui_preview <- false; ranr_parameter_file <- ""; ranr_calibration_file <- "";
        cars <- int(config["background_cars"]); privates <- int(config["private_evs"]); taxis <- int(config["electric_taxis"]);
        ranr_warmup <- float(config["warmup_minutes"]); ranr_measure <- float(config["measure_minutes"]); ranr_deadline <- float(config["deadline_minutes"]);
        step <- float(config["step_seconds"]); initial_hour <- float(config["initial_hour"]); schedule_start_hour <- initial_hour;
        consumption_kwh_km <- float(ranr_environment["consumption_kwh_km"]); charge_efficiency <- float(ranr_environment["charge_efficiency"]);
        ranr_samples <- int(config["samples"]);
        have_rush <- bool(config["rush_enabled"]); rush_extra_percent <- float(config["rush_extra_percent"]);
        ranr_ev_speed <- float(config["ev_speed_kmh"]); ranr_car_speed <- float(config["car_speed_kmh"]);
        ranr_true_compliance <- float(config["compliance"]); ranr_true_defer <- float(config["defer_probability"]);
        ranr_temperature <- float(config["temperature"]); ranr_broadcast_period <- float(config["p2p_interval"]); ranr_min_send <- float(config["min_send_seconds"])/60.0;
        ranr_delay <- float(config["delay_minutes"]); ranr_loss <- float(config["packet_loss"]); ranr_duplicate_probability <- float(config["duplicate_probability"]);
        ranr_partition_begin <- float(config["partition_begin"]); ranr_partition_end <- float(config["partition_end"]);
        ranr_behavior_case <- string(config["behavior_case"]); ranr_stabilization <- string(config["stabilization"]);
        ranr_true_decline <- float(config["decline_probability"]); ranr_abandon_after <- float(config["abandon_after_minutes"]);
        ranr_station_events_file <- string(config["station_events"]);
        ranr_run_id <- "collect_"+string(ranr_collection_seed)+"_"+string(machine_time);
        file folder <- new_folder(ranr_project_prefix+"outputs/gama_ranr/gui_calibration/runs/"+ranr_run_id); ranr_output <- folder.path;
        ranr_collection_status <- ranr_gui_bridge("prepare");
    }
    action ranr_build_gui_calibration { ranr_collection_status <- ranr_gui_bridge("build"); write ranr_collection_status; }
    action ranr_fleet_initialized {}
    action ranr_validate_gateways {
        // Explicit development study boundary: station-centred core and outer directional
        // network extrema. No claim that these are administrative city boundaries.
        point centre <- mean(list(charging_station) collect each.location);
        float radius <- max(list(charging_station) collect (each.location distance_to centre));
        ranr_central_buildings <- list(building) where (each.closest_intersection!=nil and each.location distance_to centre<=radius);
        assert !empty(ranr_central_buildings);
        building anchor <- ranr_central_buildings closest_to centre;
        list<map<string,unknown>> gateway_rows <- [];
        loop direction from: 0 to: 3 {
            list<intersection> ordered <- list(intersection) sort_by (direction=0 ? each.location.x : (direction=1 ? -each.location.x : (direction=2 ? each.location.y : -each.location.y)));
            bool found <- false;
            loop node over: ordered {
                if node in ranr_gateways or node.location distance_to centre<=radius { continue; }
                path inbound_path <- path_between(road_network,node,anchor.closest_intersection);
                path outbound_path <- path_between(road_network,anchor.closest_intersection,node);
                if inbound_path!=nil and outbound_path!=nil and !empty(inbound_path.edges) and !empty(outbound_path.edges) {
                    ranr_gateways << node;
                    gateway_rows << ["id"::node.index,"x"::node.location.x,"y"::node.location.y,"direction"::direction,
                        "inbound_metres"::sum(inbound_path.edges collect road(each).shape.perimeter),"outbound_metres"::sum(outbound_path.edges collect road(each).shape.perimeter)];
                    found <- true; break;
                }
            }
            assert found;
        }
        // Keep only destinations reachable from every gateway in both directions.
        list<building> verified <- [anchor];
        loop candidate over: ranr_central_buildings sort_by (each.location distance_to centre) {
            if candidate=anchor { continue; }
            bool connected <- true;
            loop gate over: ranr_gateways {
                if path_between(road_network,gate,candidate.closest_intersection)=nil or path_between(road_network,candidate.closest_intersection,gate)=nil { connected <- false; break; }
            }
            if connected { verified << candidate; }
            if length(verified)>=16 { break; }
        }
        ranr_central_buildings <- verified;
        save ["environment_version"::ranr_environment_version,"definition"::ranr_environment["gateway_definition"],
            "core_centre"::[centre.x,centre.y],"core_radius"::radius,"destination_buildings"::(ranr_central_buildings collect each.index),"gateways"::gateway_rows]
            to:ranr_output+"/gateway_validation.json" format:"json";
    }
    float ranr_personal_draw(list<float> values,list<float> probabilities,int id,int domain) {
        assert length(values)=length(probabilities) and min(probabilities)>=0.0 and abs(sum(probabilities)-1.0)<1e-8;
        return values[ranr_categorical(probabilities,ranr_uniform(domain,id,0))];
    }
    map<string,unknown> ranr_ev_traits(int stable_id,string kind) {
        float soc <- float(ranr_environment["initial_soc_low"])+(float(ranr_environment["initial_soc_high"])-float(ranr_environment["initial_soc_low"]))*ranr_uniform(712,stable_id,0);
        float max_kw <- [60.0,120.0,250.0][int(3.0*ranr_uniform(713,stable_id,0))];
        list<float> probabilities <- list<float>(ranr_environment[kind="taxi" ? "taxi_threshold_probabilities" : "private_threshold_probabilities"]);
        list<list<float>> intervals <- ranr_environment["soc_threshold_intervals"];
        assert length(probabilities)=length(intervals) and abs(sum(probabilities)-1.0)<1e-8 and min(probabilities)>=0.0;
        int bin <- ranr_categorical(probabilities,ranr_uniform(714,stable_id,0));
        float threshold <- intervals[bin][0]+(intervals[bin][1]-intervals[bin][0])*ranr_uniform(715,stable_id,0);
        float preferred <- ranr_personal_draw(list<float>(ranr_environment[kind="taxi" ? "taxi_target_soc_values" : "private_target_soc_values"]),list<float>(ranr_environment[kind="taxi" ? "taxi_target_probabilities" : "private_target_probabilities"]),stable_id,716);
        assert ranr_safety_soc<threshold and threshold<preferred and preferred<=100.0;
        return ["id"::stable_id,"kind"::kind,"initial_soc"::soc,"max_kw"::max_kw,"battery_capacity_kwh"::battery_capacity_kwh,"soc_request_threshold"::threshold,"soc_preferred_target"::preferred];
    }
    action ranr_configure_vehicle(vehicle v,int stable_id,string kind,bool inbound) {
        v.mobility_id <- stable_id; v.ranr_vehicle_kind <- kind; v.ranr_inbound <- inbound;
        v.is_work_car <- !inbound and kind!="taxi" and ranr_uniform(711,stable_id,0)>=0.3;
        v.is_entertainment_car <- !inbound and kind!="taxi" and !v.is_work_car;
        v.day_start <- 5.0+2.0*ranr_uniform(710,stable_id,0);
        v.day_end <- 20.0+4.0*ranr_uniform(710,stable_id,1);
        if kind!="car" {
            elecar ev <- elecar(v); map<string,unknown> traits <- ranr_ev_traits(stable_id,kind);
            ev.battery_level <- float(traits["initial_soc"]); ev.ranr_max_kw <- float(traits["max_kw"]);
            ev.soc_request_threshold <- float(traits["soc_request_threshold"]);
            ev.soc_preferred_target <- float(traits["soc_preferred_target"]); ev.soc_session_target <- ev.soc_preferred_target;
        }
        ranr_vehicle_by_id[stable_id] <- v;
    }
    building ranr_personal_building(list<building> pool,int id,int event_id) {
        return pool[min(length(pool)-1,int(ranr_uniform(740,id,event_id)*length(pool)))];
    }
    action ranr_add_activity(int id,float at,string kind,intersection destination,float activity_minutes,float shift_end) {
        map<string,unknown> item <- ["vehicle_id"::id,"sequence"::length(ranr_mobility_plans[id]),"at"::at,"kind"::kind,"node"::destination.index,"duration"::activity_minutes,"shift_end"::shift_end];
        ranr_mobility_plans[id] <- ranr_mobility_plans[id]+[item]; ranr_activity_plan << item;
    }
    action ranr_plan_personal_activities(int id,string kind,building home_place,building work_place,bool working,float begin_at,float end_at) {
        ranr_mobility_plans[id] <- [];
        int last_day <- int(ceil((initial_hour*60.0+end_at)/1440.0));
        loop day from:0 to:last_day {
            float offset <- day*1440.0-initial_hour*60.0;
            int key <- day*100;
            if kind="taxi" {
                list<float> starts <- list<float>(ranr_environment["taxi_shift_start_hours"]);
                list<float> ends <- list<float>(ranr_environment["taxi_shift_end_hours"]);
                float start <- offset+60.0*(starts[0]+(starts[1]-starts[0])*ranr_uniform(741,id,key));
                if ranr_case in ["burst","combined"] { start <- offset+420.0; }
                float finish <- offset+60.0*(ends[0]+(ends[1]-ends[0])*ranr_uniform(741,id,key+1));
                float interval <- float(ranr_environment["taxi_passenger_interval_minutes"])/(ranr_case="high" ? 1.5 : 1.0);
                float next_break <- start+float(ranr_environment["taxi_break_interval_minutes"]);
                float at <- start;
                int leg <- 0;
                loop while:at<finish {
                    if at>=next_break {
                        building stop <- ranr_personal_building(buildings_type_3,id,key+leg+2);
                        if at>=begin_at and at<end_at { do ranr_add_activity(id,at,"break",stop.closest_intersection,float(ranr_environment["taxi_break_minutes"]),finish); }
                        at <- at+float(ranr_environment["taxi_break_minutes"]); next_break <- at+float(ranr_environment["taxi_break_interval_minutes"]);
                    } else {
                        building destination <- ranr_personal_building(list(building),id,key+leg+2);
                        if at>=begin_at and at<end_at { do ranr_add_activity(id,at,"passenger",destination.closest_intersection,0.0,finish); }
                        at <- at+interval;
                    }
                    leg <- leg+1;
                }
                if finish>=begin_at and finish<end_at { do ranr_add_activity(id,finish,"home",home_place.closest_intersection,0.0,finish); }
            } else if working {
                list<float> starts <- list<float>(ranr_environment["private_work_start_hours"]);
                list<float> ends <- list<float>(ranr_environment["private_work_end_hours"]);
                float start <- offset+60.0*(starts[0]+(starts[1]-starts[0])*ranr_uniform(742,id,key));
                if ranr_case in ["burst","combined"] { start <- offset+420.0; }
                float finish <- offset+60.0*(ends[0]+(ends[1]-ends[0])*ranr_uniform(742,id,key+1));
                if start>=begin_at and start<end_at { do ranr_add_activity(id,start,"work",work_place.closest_intersection,0.0,-1.0); }
                if ranr_uniform(742,id,key+2)<0.5 {
                    building lunch <- ranr_personal_building(buildings_type_3,id,key+3);
                    if offset+720.0>=begin_at and offset+720.0<end_at {
                        do ranr_add_activity(id,offset+720.0,"personal",lunch.closest_intersection,30.0,-1.0);
                        do ranr_add_activity(id,offset+780.0,"work",work_place.closest_intersection,0.0,-1.0);
                    }
                }
                if finish>=begin_at and finish<end_at { do ranr_add_activity(id,finish,"home",home_place.closest_intersection,0.0,-1.0); }
                if ranr_uniform(742,id,key+4)<0.5 {
                    building shop <- ranr_personal_building(buildings_type_3,id,key+5);
                    if offset+1200.0>=begin_at and offset+1200.0<end_at {
                        do ranr_add_activity(id,offset+1200.0,"shopping",shop.closest_intersection,45.0,-1.0);
                        do ranr_add_activity(id,offset+1290.0,"home",home_place.closest_intersection,0.0,-1.0);
                    }
                }
            } else {
                loop slot from:0 to:2 {
                    float at <- offset+[540.0,840.0,1140.0][slot]+90.0*ranr_uniform(743,id,key+slot);
                    building destination <- ranr_personal_building(buildings_type_3,id,key+slot+5);
                    if at>=begin_at and at<end_at {
                        do ranr_add_activity(id,at,"personal",destination.closest_intersection,45.0,-1.0);
                        do ranr_add_activity(id,at+120.0,"home",home_place.closest_intersection,0.0,-1.0);
                    }
                }
            }
        }
        ranr_mobility_plans[id] <- ranr_mobility_plans[id] sort_by float(each["at"]);
    }
    action ranr_initialize_fleet {
        loop node over:list(intersection) { ranr_nodes_by_id[node.index] <- node; }
        int n <- 0;
        loop v over:list(car) { do ranr_configure_vehicle(v,1000+n,"car",false); n <- n+1; }
        n <- 0; loop v over:list(private_ev) { do ranr_configure_vehicle(v,10000+n,"private",false); n <- n+1; }
        n <- 0; loop v over:list(taxi_ev) { do ranr_configure_vehicle(v,20000+n,"taxi",false); n <- n+1; }
        assert length(ranr_city_vehicles)=cars+privates+taxis;
        do ranr_validate_gateways;
        float traffic_end <- ranr_warmup+ranr_measure+ranr_deadline;
        loop ev over:ev_population {
            do ranr_plan_personal_activities(ev.mobility_id,ev.ranr_vehicle_kind,ev.home,ev.work_place,ev.is_work_car,0.0,traffic_end);
            ev.activity_schedule <- ranr_mobility_plans[ev.mobility_id];
        }
        int last_day <- int(ceil((initial_hour*60.0+traffic_end)/1440.0));
        if have_rush {
            loop day from:0 to:last_day {
                loop window from:0 to:1 {
                    list<list<float>> windows <- ranr_environment["rush_windows_hours"];
                    float start_at <- day*1440.0+windows[window][0]*60.0-initial_hour*60.0;
                    float close_at <- day*1440.0+windows[window][1]*60.0-initial_hour*60.0;
                    if close_at<=0.0 or start_at>=traffic_end { continue; }
                    loop kind_index from:0 to:2 {
                        string kind <- ["car","private","taxi"][kind_index];
                        int cap <- int(floor([cars,privates,taxis][kind_index]*rush_extra_percent/100.0));
                        if cap=0 { continue; }
                        loop slot from:0 to:cap-1 {
                            int id <- 1000000+day*1000000+window*100000+kind_index*20000+slot;
                            float at <- start_at+(close_at-start_at)*(slot+ranr_uniform(730,id,0))/cap;
                            if at<0.0 or at>=traffic_end { continue; }
                            int gate <- int(length(ranr_gateways)*ranr_uniform(731,id,0));
                            float depart <- close_at+float(ranr_environment["inbound_dwell_minutes"])*ranr_uniform(732,id,0);
                            int destination <- int(length(ranr_central_buildings)*ranr_uniform(734,id,0));
                            ranr_inbound_plan << ["id"::id,"kind"::kind,"at"::at,"depart"::depart,"gateway"::gate,"destination"::destination];
                            if kind!="car" {
                                ranr_mobility_plans[id] <- [];
                                do ranr_add_activity(id,at,"visitor",ranr_central_buildings[destination].closest_intersection,0.0,depart);
                                do ranr_add_activity(id,depart,"exit",ranr_gateways[gate],0.0,depart);
                            }
                        }
                    }
                }
            }
        }
        ranr_inbound_plan <- ranr_inbound_plan sort_by float(each["at"]);
        do ranr_register_exposure;
        do ranr_register_activities;
        save ranr_inbound_plan to:ranr_output+"/traffic_plan.json" format:"json";
        save ranr_activity_plan to:ranr_output+"/activity_plan.json" format:"json";
        list<map<string,unknown>> traits <- ev_population collect ranr_ev_traits(each.mobility_id,each.ranr_vehicle_kind);
        loop entry over:ranr_inbound_plan where (each["kind"]!="car") { traits << ranr_ev_traits(int(entry["id"]),string(entry["kind"])); }
        save traits to:ranr_output+"/vehicle_traits.json" format:"json";
        save "at,vehicle_id,kind,event,gateway,x,y,soc\n" to:ranr_output+"/traffic.csv" format:"text";
        save "at,vehicle_id,kind,inbound,state,session,soc,total_metres,total_charged_kwh,intent_id,threshold,target,activity,passenger,x,y\n" to:ranr_output+"/vehicles.csv" format:"text";
        save "at,vehicle_id,event,activity,sequence,x,y,soc\n" to:ranr_output+"/activity_events.csv" format:"text";
        save "at,intent_id,vehicle_id,event,reason,attempt\n" to:ranr_output+"/intent_events.csv" format:"text";
        save (ranr_city_vehicles collect ["id"::each.mobility_id,"kind"::each.ranr_vehicle_kind,"soc"::(each.is_ev ? elecar(each).battery_level : -1.0),"x"::each.location.x,"y"::each.location.y,
            "battery_capacity_kwh"::battery_capacity_kwh,"soc_request_threshold"::(each.is_ev ? elecar(each).soc_request_threshold : -1.0),"soc_preferred_target"::(each.is_ev ? elecar(each).soc_preferred_target : -1.0)]) to:ranr_output+"/initial_fleet.json" format:"json";
        ranr_fleet_ready <- true;
        do ranr_fleet_initialized;
    }
    action ranr_spawn_inbound(map<string,unknown> entry) {
        string kind <- string(entry["kind"]); int id <- int(entry["id"]);
        int cap <- int(floor((kind="car" ? cars : (kind="private" ? privates : taxis))*rush_extra_percent/100.0));
        int count <- length(ranr_city_vehicles where (each.ranr_inbound and each.ranr_vehicle_kind=kind));
        int gate <- int(entry["gateway"]);
        if count>=cap {
            ranr_traffic_buffer <- ranr_traffic_buffer+time/60.0+","+id+","+kind+",capacity_blocked,"+gate+",-1,-1,-1\n"; return nil;
        }
        intersection origin <- ranr_gateways[gate]; building central_target <- ranr_central_buildings[int(length(ranr_central_buildings)*ranr_uniform(734,id,0))];
        vehicle v <- nil;
        if kind="car" { create car with:[location::origin.location,home::central_target] { v <- self; } }
        else if kind="private" { create private_ev with:[location::origin.location,home::central_target,all_stations::list(charging_station)] { v <- self; } }
        else { create taxi_ev with:[location::origin.location,home::central_target,all_stations::list(charging_station)] { v <- self; } }
        do ranr_configure_vehicle(v,id,kind,true);
        v.ranr_exit_id <- gate; v.ranr_depart_at <- float(entry["depart"]); v.target <- central_target;
        if kind="car" { ask v { do compute_path graph:road_network target:central_target.closest_intersection; } }
        else { elecar(v).activity_schedule <- ranr_mobility_plans[id]; }
        ranr_inbound_created <- ranr_inbound_created+1;
        ranr_traffic_buffer <- ranr_traffic_buffer+time/60.0+","+id+","+kind+",entered,"+gate+","+v.location.x+","+v.location.y+","+(v.is_ev ? elecar(v).battery_level : -1.0)+"\n";
    }

    intersection ranr_activity_destination(int node_id) { return ranr_nodes_by_id[node_id]; }
    intersection ranr_vehicle_origin(vehicle v) { return access_intersections closest_to v; }
    float ranr_nearest_station_metres(intersection node) {
        if !((ranr_station_distance_by_node contains_key node.index)) {
            float nearest <- -1.0;
            loop station over:list(charging_station) {
                path route <- path_between(road_network,node,station.closest_intersection);
                if route!=nil { float metres <- sum(route.edges collect each.perimeter); nearest <- nearest<0.0 ? metres : min(nearest,metres); }
            }
            ranr_station_distance_by_node[node.index] <- nearest;
        }
        return ranr_station_distance_by_node[node.index];
    }
    float ranr_trip_energy(elecar ev) {
        if ev.final_target=nil { return 0.0; }
        return ev.remaining_trip_metres()*consumption_kwh_km/1000.0;
    }
    float ranr_planned_energy(elecar ev) {
        float energy <- ranr_trip_energy(ev);
        if ev.final_target!=nil {
            if ev.ranr_energy_checked_path!=ev.current_path {
                ev.ranr_destination_station_metres <- ranr_nearest_station_metres(intersection(ev.final_target));
                ev.ranr_energy_checked_path <- ev.current_path;
            }
            if ev.ranr_destination_station_metres<0.0 { return battery_capacity_kwh+1.0; }
            energy <- energy+ev.ranr_destination_station_metres*consumption_kwh_km/1000.0;
        }
        return energy+ranr_safety_soc*battery_capacity_kwh/100.0;
    }
    float ranr_trip_requirement(elecar ev) { return ranr_planned_energy(ev); }
    float ranr_shift_energy(elecar ev) {
        // Estimate duty until the next published break. Future passenger destinations
        // are not inspected; only a booking already visible to this taxi may be routed.
        float at <- time/60.0;
        float until <- at+float(ranr_environment["taxi_break_interval_minutes"]);
        float known_trip <- 0.0;
        if ev.activity_cursor<length(ev.activity_schedule) {
            map<string,unknown> upcoming <- ev.activity_schedule[ev.activity_cursor];
            if float(upcoming["at"])-at<=float(ranr_environment["taxi_booking_notice_minutes"]) {
                path route <- path_between(road_network,ranr_vehicle_origin(ev),ranr_nodes_by_id[int(upcoming["node"])]);
                if route!=nil { known_trip <- sum(route.edges collect each.perimeter)*consumption_kwh_km/1000.0; }
            }
            loop k from:ev.activity_cursor to:length(ev.activity_schedule)-1 {
                map<string,unknown> activity <- ev.activity_schedule[k];
                if activity["kind"] in ["break","home","exit"] { until <- min(until,max(at,float(activity["at"]))); break; }
            }
        }
        float estimated <- max(0.0,until-at)/60.0*float(ranr_environment["taxi_expected_km_per_operating_hour"])*consumption_kwh_km;
        return max(known_trip,estimated)+ranr_safety_soc*battery_capacity_kwh/100.0;
    }
    bool ranr_allow_mobility(elecar ev) {
        if !ranr_enabled or !ranr_fleet_ready { return true; }
        if ev.ranr_road_clear_pending { ev.ranr_energy_hold <- false; return true; }
        if ev.needs_charging { ev.ranr_energy_hold <- ev.session_state!="en_route"; return !ev.ranr_energy_hold; }
        // A passenger or personal trip already accepted with adequate energy is completed.
        if ev.activity_in_progress { ev.ranr_energy_hold <- false; return true; }
        float required <- ranr_planned_energy(ev);
        bool insufficient <- ev.final_target!=nil and required>ev.battery_level*battery_capacity_kwh/100.0+1e-9;
        bool low <- ev.battery_level<=ev.soc_request_threshold;
        bool open_intent <- ev.charging_intent_id!="" and (ranr_intents contains_key ev.charging_intent_id) and ranr_intents[ev.charging_intent_id]["status"]="open";
        if insufficient { ev.charging_need_reason <- "trip_energy"; }
        else if low and ev.charging_need_reason="" { ev.charging_need_reason <- "low_soc"; }
        ev.ranr_energy_hold <- insufficient or open_intent or (low and ev.charging_intent_id="");
        return !ev.ranr_energy_hold;
    }
    action ranr_register_exposure {
        float minutes <- float(privates+taxis)*ranr_measure;
        loop ev over:ev_population { ranr_exposure_ids[ev.mobility_id] <- true; }
        loop entry over:ranr_inbound_plan where (each["kind"]!="car") {
            float overlap <- max(0.0,min(float(entry["depart"]),ranr_warmup+ranr_measure)-max(float(entry["at"]),ranr_warmup));
            minutes <- minutes+overlap;
            if overlap>0.0 { ranr_exposure_ids[int(entry["id"])] <- true; }
        }
        ranr_planned_ev_days <- minutes/1440.0;
        save ["planned_ev_days"::ranr_planned_ev_days,"measurement_start"::ranr_warmup,"measurement_end"::(ranr_warmup+ranr_measure)] to:ranr_output+"/planned_exposure.json" format:"json";
    }
    action ranr_register_activities {
        ranr_activity_plan <- [];
        map<string,float> route_energy <- [];
        loop id over:ranr_mobility_plans.keys {
            list<map<string,unknown>> plan <- ranr_mobility_plans[id];
            plan <- plan sort_by float(each["at"]);
            intersection origin <- nil;
            string vehicle_kind <- "private";
            if ranr_vehicle_by_id contains_key id { origin <- ranr_vehicle_by_id[id].home.closest_intersection; vehicle_kind <- ranr_vehicle_by_id[id].ranr_vehicle_kind; }
            else { list<map<string,unknown>> entries <- ranr_inbound_plan where (int(each["id"])=id); if !empty(entries) { origin <- ranr_gateways[int(entries[0]["gateway"])]; vehicle_kind <- string(entries[0]["kind"]); } }
            loop item over:plan {
                string key <- string(id)+":"+string(item["sequence"]);
                intersection destination_node <- ranr_nodes_by_id[int(item["node"])];
                float required <- -1.0;
                if origin!=nil {
                    string route_key <- string(origin.index)+":"+string(destination_node.index);
                    if !(route_energy contains_key route_key) { path route <- path_between(road_network,origin,destination_node); route_energy[route_key] <- route=nil ? -1.0 : sum(route.edges collect road(each).shape.perimeter)*consumption_kwh_km/1000.0; }
                    required <- route_energy[route_key];
                }
                item["vehicle_kind"] <- vehicle_kind; item["activity_id"] <- key; item["origin_node"] <- origin=nil ? -1 : origin.index; item["planned_energy_kwh"] <- required;
                map<string,unknown> result <- ranr_record(item);
                result["status"] <- "unresolved"; result["actual_start"] <- nil; result["actual_completion"] <- nil; result["reason"] <- "not_observed";
                ranr_activity_outcomes[key] <- result;
                ranr_activity_plan << item;
                origin <- destination_node;
            }
        }
    }
    action ranr_activity_event(elecar ev,string event_name) {
        ranr_activity_buffer <- ranr_activity_buffer+time/60.0+","+ev.mobility_id+","+event_name+","+ev.current_activity+","+ev.activity_cursor+","+ev.location.x+","+ev.location.y+","+ev.battery_level+"\n";
        if ev.activity_cursor<length(ev.activity_schedule) {
            map<string,unknown> item <- ev.activity_schedule[ev.activity_cursor];
            string key <- string(ev.mobility_id)+":"+string(item["sequence"]);
            if ranr_activity_outcomes contains_key key {
                map<string,unknown> result <- ranr_activity_outcomes[key];
                if event_name="departed" { result["actual_start"] <- time/60.0; }
                if event_name="arrived" { result["status"] <- "completed"; result["actual_completion"] <- time/60.0; result["reason"] <- "observed_arrival"; }
                if event_name in ["missed_service","route_unavailable","trip_exceeds_battery_capacity"] { result["status"] <- "missed"; result["reason"] <- event_name; }
            }
        }
        ev.charging_activity_event <- true;
    }
    // Integrate a single mutually exclusive intent state before every transition.
    action ranr_integrate_intent(elecar ev,float at) {
        if ev.charging_intent_id="" or !(ranr_intents contains_key ev.charging_intent_id) { return nil; }
        map<string,unknown> intent <- ranr_intents[ev.charging_intent_id];
        if intent["status"]!="open" { return nil; }
        float begin <- float(intent["state_since"]);
        assert at>=begin-1e-7;
        if at>begin+1e-10 {
            string state_key <- string(intent["time_state"])+"_min";
            intent[state_key] <- float(intent[state_key])+at-begin;
            ranr_time_intervals << ["intent_id"::ev.charging_intent_id,"state"::intent["time_state"],"begin"::begin,"end"::at];
        }
        intent["state_since"] <- at;
    }
    action ranr_intent_transition(elecar ev,string state_name,float at) {
        do ranr_integrate_intent(ev,at);
        if ev.charging_intent_id!="" and ranr_intents contains_key ev.charging_intent_id {
            map<string,unknown> intent <- ranr_intents[ev.charging_intent_id];
            if intent["status"]="open" { intent["time_state"] <- state_name; }
        }
    }
    action ranr_queue_arrived(elecar ev) {
        if ev.charging_intent_id!="" and ranr_intents contains_key ev.charging_intent_id { ranr_intents[ev.charging_intent_id]["queue_eligible"] <- true; }
    }
    action ranr_deadline_snapshot(elecar ev,float at) {
        if ev.charging_intent_id="" or !(ranr_intents contains_key ev.charging_intent_id) { return nil; }
        map<string,unknown> intent <- ranr_intents[ev.charging_intent_id];
        if intent["status"]!="open" or bool(intent["deadline_observed"]) or at<float(intent["deadline"])-1e-7 { return nil; }
        float consumed <- (ev.ranr_lifetime_metres-float(intent["initial_metres"]))*consumption_kwh_km/1000.0;
        float delivered <- ev.ranr_lifetime_charged_kwh-float(intent["initial_charged_kwh"]);
        float required <- float(intent["initial_required_kwh"])+consumed;
        intent["deadline_observed"] <- true; intent["deadline_missed"] <- required-delivered>ranr_energy_tolerance;
        intent["deadline_remaining_kwh"] <- max(0.0,required-delivered); intent["deadline_snapshot_at"] <- at;
        do ranr_intent_event(ev,"deadline_observed",bool(intent["deadline_missed"]) ? "not_energy_complete" : "energy_complete");
    }
    action ranr_intent_event(elecar ev,string event_name,string reason) {
        ranr_intent_buffer <- ranr_intent_buffer+time/60.0+","+ev.charging_intent_id+","+ev.mobility_id+","+event_name+","+reason+","+ev.charging_attempt_count+"\n";
    }
    action ranr_open_intent(elecar ev,string reason) {
        if ev.charging_intent_id!="" or time/60.0>=ranr_warmup+ranr_measure { return nil; }
        ev.charging_intent_sequence <- ev.charging_intent_sequence+1;
        ev.charging_intent_id <- "intent_"+ev.mobility_id+"_"+ev.charging_intent_sequence;
        ev.charging_need_reason <- reason; ev.charging_attempt_count <- 0; ev.charging_deferred_reason <- "";
        ev.ranr_next_energy_attempt <- time/60.0; ev.charging_activity_event <- true;
        float required <- ev.activity_prepared ? ranr_planned_energy(ev) : 0.0;
        if reason="shift_energy" { required <- max(required,ev.charging_shift_energy); }
        ev.soc_session_target <- min(100.0,max(ev.soc_preferred_target,100.0*required/battery_capacity_kwh));
        float at <- time/60.0;
        ranr_intents[ev.charging_intent_id] <- ranr_record(["intent_id"::ev.charging_intent_id,"key"::length(ranr_intents)+1,"vehicle_id"::ev.mobility_id,"kind"::ev.ranr_vehicle_kind,
            "at"::at,"deadline"::(at+360.0),"cause"::reason,"soc_at_need"::ev.battery_level,"threshold"::ev.soc_request_threshold,
            "target_soc"::ev.soc_session_target,"trip_energy_kwh"::required,"activity"::ev.current_activity,"measured"::(at>=ranr_warmup and at<ranr_warmup+ranr_measure),
            "initial_required_kwh"::max(0.0,(ev.soc_session_target-ev.battery_level)*battery_capacity_kwh/100.0),
            "battery_capacity_kwh"::battery_capacity_kwh,"initial_battery_kwh"::(ev.battery_level*battery_capacity_kwh/100.0),"deadline_observed"::false,"deadline_missed"::false,"deadline_remaining_kwh"::nil,"deadline_snapshot_at"::nil,
            "state_since"::at,"time_state"::"deferred","deferred_min"::0.0,"retry_delay_min"::0.0,"other_elapsed_min"::0.0,
            "initial_metres"::ev.ranr_lifetime_metres,"initial_charged_kwh"::ev.ranr_lifetime_charged_kwh,"travel_min"::0.0,"waiting_min"::0.0,"charging_min"::0.0,"queue_eligible"::false,"attempts"::0,"deferred_reason"::"","status"::"open"]);
        if !ev.activity_in_progress { ev.ranr_energy_hold <- true; }
        do ranr_intent_event(ev,"created",reason);
    }
    action ranr_close_intent(elecar ev,string status,float at) {
        if ev.charging_intent_id="" or !(ranr_intents contains_key ev.charging_intent_id) { return nil; }
        map<string,unknown> intent <- ranr_intents[ev.charging_intent_id];
        if intent["status"]!="open" { return nil; }
        do ranr_integrate_intent(ev,at);
        do ranr_deadline_snapshot(ev,at);
        float energy <- ev.ranr_lifetime_charged_kwh-float(intent["initial_charged_kwh"]);
        float consumed <- (ev.ranr_lifetime_metres-float(intent["initial_metres"]))*consumption_kwh_km/1000.0;
        float required <- float(intent["initial_required_kwh"])+consumed;
        float final_energy <- ev.battery_level*battery_capacity_kwh/100.0;
        assert abs(final_energy-(float(intent["initial_battery_kwh"])-consumed+energy))<=ranr_energy_tolerance+1e-8*abs(final_energy);
        assert energy<=required+ranr_energy_tolerance;
        bool complete <- required-energy<=ranr_energy_tolerance;
        assert status!="completed" or complete;
        string terminal <- status="completed" ? "completed" : (status="stranded" ? "failed" : "unresolved");
        map<string,unknown> result <- ranr_record(intent);
        result["schema"] <- "charging-intent-outcome-5"; result["issued_min"] <- intent["at"]; result["finished_min"] <- at;
        result["observation_end"] <- at; result["actual_completion_time"] <- terminal="completed" ? at : nil;
        result["completion_time_min"] <- terminal="completed" ? at-float(intent["at"]) : nil;
        result["status"] <- terminal; result["terminal_reason"] <- status;
        result["requested_kwh"] <- required; result["delivered_kwh"] <- energy; result["consumed_kwh"] <- consumed;
        result["grid_kwh"] <- energy/charge_efficiency; result["charging_loss_kwh"] <- energy/charge_efficiency-energy;
        result["final_battery_kwh"] <- final_energy; result["energy_complete"] <- complete;
        result["deadline_missed"] <- bool(intent["deadline_missed"]) or (terminal="completed" and at>float(intent["deadline"])+1e-7) or (!complete and at>=float(intent["deadline"])-1e-7);
        result["on_time"] <- terminal="completed" and at<=float(intent["deadline"])+1e-7;
        result["right_censored"] <- terminal="unresolved";
        result["elapsed_min"] <- at-float(intent["at"]); result["service_time_min"] <- at-float(intent["at"]);
        result["queue_eligible"] <- bool(intent["queue_eligible"]);
        result["final_soc"] <- ev.battery_level; result["measured"] <- float(intent["at"])>=ranr_warmup and float(intent["at"])<ranr_warmup+ranr_measure;
        result["attempt_ids"] <- ranr_attempts where (each["intent_id"]=ev.charging_intent_id) collect string(each["attempt_id"]);
        ranr_intent_outcomes[ev.charging_intent_id] <- result;
        intent["status"] <- terminal;
        do ranr_intent_event(ev,"resolved",terminal);
        if terminal="completed" {
            ev.charging_intent_id <- ""; ev.charging_need_reason <- ""; ev.charging_deferred_reason <- "";
            ev.activity_prepared <- false; ev.ranr_energy_hold <- false;
        } else { ev.ranr_energy_hold <- !ev.activity_in_progress; }
    }
    action ranr_terminal_intent_event(elecar ev,string status,float at) {
        if ev.charging_intent_id="" or !(ranr_intents contains_key ev.charging_intent_id) { return nil; }
        map<string,unknown> intent <- ranr_intents[ev.charging_intent_id];
        if intent["status"]!="open" { return nil; }
        if status="completed" { do ranr_close_intent(ev,status,at); }
        else if status="stranded" { do ranr_close_intent(ev,status,at); }
        else {
            do ranr_intent_transition(ev,"retry_delay",at);
            ev.charging_deferred_reason <- status; intent["deferred_reason"] <- status;
            ev.ranr_next_energy_attempt <- at+min(ranr_energy_retry_max_minutes,ranr_energy_retry_minutes*2.0^min(4,max(0,ev.charging_attempt_count-1)));
            ev.ranr_energy_hold <- !ev.activity_in_progress;
            do ranr_intent_event(ev,"deferred",status);
        }
    }
    action ranr_start_attempt(elecar ev) {
        map<string,unknown> intent <- ranr_intents[ev.charging_intent_id];
        if ev.needs_charging or ev.is_charging or ev.activity_in_progress or intent["status"]!="open" { return nil; }
        ranr_attempt_sequence <- ranr_attempt_sequence+1;
        ev.ranr_demand_key <- ranr_attempt_sequence;
        ev.charging_attempt_count <- ev.charging_attempt_count+1;
        ev.ranr_participating <- true; ev.ranr_measured <- bool(intent["measured"]);
        ev.ranr_deadline_at <- float(intent["deadline"]);
        do ranr_intent_transition(ev,"other_elapsed",time/60.0);
        ev.soc_session_target <- max(ev.soc_session_target,float(intent["target_soc"]));
        ev.requested_energy <- max(0.0,(ev.soc_session_target-ev.battery_level)*battery_capacity_kwh/100.0);
        intent["attempts"] <- ev.charging_attempt_count;
        intent["deferred_reason"] <- ""; ev.charging_deferred_reason <- "";
        ranr_attempts << ranr_record(["attempt_id"::("ranr_"+ranr_attempt_sequence),"key"::ranr_attempt_sequence,"request_id"::("ranr_"+ranr_attempt_sequence),"intent_id"::ev.charging_intent_id,"vehicle_id"::ev.mobility_id,"kind"::ev.ranr_vehicle_kind,"at"::(time/60.0),"deadline"::ev.ranr_deadline_at,"cause"::intent["cause"],"attempt"::ev.charging_attempt_count,"measured"::intent["measured"],"activity"::ev.current_activity,"passenger"::ev.taxi_has_passenger,"retry_trigger"::ev.charging_retry_trigger,"source"::"physical_energy"]);
        ev.charging_last_attempt_soc <- ev.battery_level; ev.charging_activity_event <- false;
        ask ev { do begin_request; }
        do ranr_intent_event(ev,"requested",ev.charging_need_reason);
    }
    action ranr_check_energy(float at) {
        loop ev over:ev_population sort_by each.mobility_id {
            if ev.ranr_stranded and ranr_exposure_ids contains_key ev.mobility_id { ranr_stranded_ids[ev.mobility_id] <- true; }
            do ranr_deadline_snapshot(ev,at);
            if ev.ranr_stranded { if ev.charging_intent_id!="" { do ranr_close_intent(ev,"stranded",at); } continue; }
            if ev.battery_level<=0.0 { continue; }
            if ev.ranr_road_clear_pending { continue; }
            if ev.needs_charging or ev.is_charging { continue; }
            if ev.charging_intent_id="" and at>=ranr_warmup+ranr_measure { continue; }
            bool threshold_crossed <- ev.battery_level<=ev.soc_request_threshold and (ev.charging_last_checked_soc>ev.soc_request_threshold or ev.charging_last_checked_soc<0.0);
            bool due <- at>=ev.ranr_next_energy_attempt;
            bool new_path <- ev.activity_prepared and ev.current_path!=ev.charging_last_checked_path;
            bool check_shift <- ev.ranr_vehicle_kind="taxi" and ev.activity_cursor<length(ev.activity_schedule) and !ev.activity_in_progress and ev.charging_intent_id="";
            if check_shift {
                map<string,unknown> upcoming <- ev.activity_schedule[ev.activity_cursor];
                check_shift <- upcoming["kind"]="passenger" and float(upcoming["at"])-at<=float(ranr_environment["taxi_booking_notice_minutes"]) and float(upcoming["at"])-at>=0.0 and ev.activity_cursor!=ev.charging_last_shift_cursor;
            }
            if ev.charging_intent_id="" and !threshold_crossed and !new_path and !check_shift and !ev.charging_activity_event and ev.charging_need_reason="" { continue; }
            ev.charging_last_checked_soc <- ev.battery_level;
            ev.charging_last_checked_path <- ev.current_path;
            if ev.charging_intent_id="" {
                string reason <- ev.charging_need_reason;
                if threshold_crossed { reason <- "low_soc"; }
                if new_path and ranr_planned_energy(ev)>ev.battery_level*battery_capacity_kwh/100.0+1e-9 { reason <- "trip_energy"; }
                if check_shift {
                    ev.charging_last_shift_cursor <- ev.activity_cursor;
                    ev.charging_shift_energy <- ranr_shift_energy(ev);
                    if ev.charging_shift_energy>ev.battery_level*battery_capacity_kwh/100.0 and ev.battery_level<ev.soc_preferred_target { reason <- "shift_energy"; }
                }
                if reason!="" and at<ranr_warmup+ranr_measure {
                    // Eligibility is independently retained even if later exports lose an intent.
                    string need_id <- "intent_"+ev.mobility_id+"_"+(ev.charging_intent_sequence+1);
                    ranr_need_records << ["intent_id"::need_id,"vehicle_id"::ev.mobility_id,"at"::at,"soc"::ev.battery_level,"reason"::reason];
                    do ranr_open_intent(ev,reason);
                    assert ev.charging_intent_id=need_id;
                }
            }
            if ev.charging_intent_id="" { ev.charging_activity_event <- false; continue; }
            map<string,unknown> intent <- ranr_intents[ev.charging_intent_id];
            if intent["status"]!="open" { continue; }
            do ranr_deadline_snapshot(ev,at);
            if ev.activity_in_progress {
                string reason <- ev.taxi_has_passenger ? "passenger_trip" : "activity_in_progress";
                if ev.charging_deferred_reason!=reason { do ranr_intent_event(ev,"deferred",reason); }
                ev.charging_deferred_reason <- reason; intent["deferred_reason"] <- reason;
                continue;
            }
            ev.ranr_energy_hold <- true;
            bool urgent <- ev.battery_level<=ranr_energy_urgent_soc and ev.charging_last_attempt_soc>ranr_energy_urgent_soc;
            if due or (ev.charging_activity_event and at>ev.request_time) or urgent {
                ev.charging_retry_trigger <- ev.charging_attempt_count=0 ? "new_intent" : (urgent ? "increased_urgency" : (ev.charging_activity_event ? "activity_or_availability" : "cooldown"));
                do ranr_start_attempt(ev);
            }
        }
    }
    action ranr_finish_intents(float at) {
        loop ev over:ev_population where (each.charging_intent_id!="") {
            if ev.needs_charging {
                if ev.session_state="waiting" { ev.waiting_time <- ev.ranr_previous_wait+max(0.0,at-ev.arrival_time); }
                do ranr_finalize(ev,"unresolved",at);
                do record_event(ev,"unresolved");
            }
            do ranr_close_intent(ev,ev.ranr_stranded ? "stranded" : "unresolved",at);
        }
        save ranr_time_intervals to:ranr_output+"/intent_time_intervals.json" format:"json";
        save list(ranr_activity_outcomes.values) to:ranr_output+"/mobility_outcomes.json" format:"json";
    }
    action ranr_fleet_tick(float at) {
        loop while:ranr_inbound_cursor<length(ranr_inbound_plan) and float(ranr_inbound_plan[ranr_inbound_cursor]["at"])<=at {
            do ranr_spawn_inbound(ranr_inbound_plan[ranr_inbound_cursor]); ranr_inbound_cursor <- ranr_inbound_cursor+1;
        }
        loop v over:copy(ranr_city_vehicles) where (each.ranr_inbound and !each.ranr_stranded and !each.needs_charging and !each.is_charging and each.final_target=nil and at>=each.ranr_depart_at) {
            intersection exit_node <- ranr_gateways[v.ranr_exit_id];
            bool open_intent <- v.is_ev and elecar(v).charging_intent_id!="" and ranr_intents[elecar(v).charging_intent_id]["status"]="open";
            if open_intent { continue; }
            if v.location distance_to exit_node.location<2.0 {
                ranr_traffic_buffer <- ranr_traffic_buffer+at+","+v.mobility_id+","+v.ranr_vehicle_kind+",exited,"+v.ranr_exit_id+","+v.location.x+","+v.location.y+","+(v.is_ev ? elecar(v).battery_level : -1.0)+"\n";
                remove key:v.mobility_id from:ranr_vehicle_by_id;
                ask v { do unregister; do die; } ranr_inbound_exited <- ranr_inbound_exited+1;
            } else if !v.is_ev {
                v.ranr_exiting <- true; ask v { do compute_path graph:road_network target:exit_node; }
            }
        }
        do ranr_check_energy(at);
        if at>=ranr_next_vehicle_log or at>=ranr_warmup+ranr_measure+ranr_deadline {
            assert length(ranr_city_vehicles where (!each.ranr_inbound))=cars+privates+taxis;
            assert length(ranr_city_vehicles)<=cars+privates+taxis+int(floor(cars*rush_extra_percent/100.0))+int(floor(privates*rush_extra_percent/100.0))+int(floor(taxis*rush_extra_percent/100.0));
            loop v over:ranr_city_vehicles {
                string state <- v.ranr_stranded ? "stranded" : (v.ranr_energy_hold ? "energy_hold" : (v.final_target=nil ? "parked" : "driving"));
                ranr_vehicle_buffer <- ranr_vehicle_buffer+at+","+v.mobility_id+","+v.ranr_vehicle_kind+","+v.ranr_inbound+","+state+","+(v.is_ev ? elecar(v).session_state : "none")+","+(v.is_ev ? elecar(v).battery_level : -1.0)+","+v.ranr_lifetime_metres+","+v.ranr_lifetime_charged_kwh+","+
                    (v.is_ev ? elecar(v).charging_intent_id : "")+","+(v.is_ev ? elecar(v).soc_request_threshold : -1.0)+","+(v.is_ev ? elecar(v).soc_session_target : -1.0)+","+(v.is_ev ? elecar(v).current_activity : "traffic")+","+(v.is_ev ? elecar(v).taxi_has_passenger : false)+","+v.location.x+","+v.location.y+"\n";
            }
            ranr_next_vehicle_log <- at+60.0;
        }
    }
    action ranr_flush_fleet {
        save ranr_need_records to:ranr_output+"/charging_needs.json" format:"json";
        save list(ranr_intents.values) to:ranr_output+"/charging_intents.json" format:"json";
        save ranr_attempts to:ranr_output+"/request_attempts.json" format:"json";
        save list(ranr_intent_outcomes.values) to:ranr_output+"/intent_outcomes.json" format:"json";
        if ranr_traffic_buffer!="" { save ranr_traffic_buffer to:ranr_output+"/traffic.csv" format:"text" rewrite:false; ranr_traffic_buffer <- ""; }
        if ranr_vehicle_buffer!="" { save ranr_vehicle_buffer to:ranr_output+"/vehicles.csv" format:"text" rewrite:false; ranr_vehicle_buffer <- ""; }
        if ranr_activity_buffer!="" { save ranr_activity_buffer to:ranr_output+"/activity_events.csv" format:"text" rewrite:false; ranr_activity_buffer <- ""; }
        if ranr_intent_buffer!="" { save ranr_intent_buffer to:ranr_output+"/intent_events.csv" format:"text" rewrite:false; ranr_intent_buffer <- ""; }
    }

}
