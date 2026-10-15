model ranr_persistent_fleet
import "../ChargingService.gaml"

global {
    list<vehicle> ranr_city_vehicles -> agents of_generic_species vehicle;
    list<intersection> ranr_gateways <- [];
    list<building> ranr_central_buildings <- [];
    map<int,vehicle> ranr_vehicle_by_id <- [];
    map<int,string> ranr_planned_kinds <- [];
    list<map<string,unknown>> ranr_inbound_plan <- [];
    list<map<string,unknown>> ranr_opportunities <- [];
    int ranr_inbound_cursor <- 0;
    int ranr_opportunity_cursor <- 0;
    list<map<string,unknown>> ranr_opportunity_ledger <- [];
    int ranr_opportunity_count <- 0;
    int ranr_activated_count <- 0;
    int ranr_inbound_created <- 0;
    int ranr_inbound_exited <- 0;
    int ranr_burst_shortfall <- 0;
    float ranr_next_vehicle_log <- 0.0;
    string ranr_opportunity_buffer <- "";
    string ranr_traffic_buffer <- "";
    string ranr_vehicle_buffer <- "";

    float ranr_base_rate -> (privates*ranr_private_frequency+taxis*ranr_taxi_frequency)/1440.0;
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
        ranr_samples <- int(config["samples"]); ranr_private_frequency <- float(config["private_frequency"]); ranr_taxi_frequency <- float(config["taxi_frequency"]);
        ranr_soc_threshold <- float(config["soc_threshold"]); target_soc <- float(config["target_soc"]);
        have_rush <- bool(config["rush_enabled"]); rush_extra_percent <- float(config["rush_extra_percent"]);
        ranr_ev_speed <- float(config["ev_speed_kmh"]); ranr_car_speed <- float(config["car_speed_kmh"]);
        ranr_true_compliance <- float(config["compliance"]); ranr_true_defer <- float(config["defer_probability"]); ranr_burst_size <- int(config["burst_size"]);
        ranr_temperature <- float(config["temperature"]); ranr_broadcast_period <- float(config["p2p_interval"]); ranr_min_send <- float(config["min_send_seconds"])/60.0;
        ranr_delay <- float(config["delay_minutes"]); ranr_loss <- float(config["packet_loss"]); ranr_duplicate_probability <- float(config["duplicate_probability"]);
        ranr_partition_begin <- float(config["partition_begin"]); ranr_partition_end <- float(config["partition_end"]);
        ranr_behavior_case <- string(config["behavior_case"]); ranr_stabilization <- string(config["stabilization"]);
        ranr_failure_beta <- float(config["failure_beta"]); ranr_energy_beta <- float(config["energy_beta"]);
        ranr_true_decline <- float(config["decline_probability"]); ranr_abandon_after <- float(config["abandon_after_minutes"]);
        ranr_station_events_file <- string(config["station_events"]);
        ranr_run_id <- "collect_"+string(ranr_collection_seed)+"_"+string(machine_time);
        file folder <- new_folder(ranr_project_prefix+"outputs/gama_ranr/gui_calibration/runs/"+ranr_run_id); ranr_output <- folder.path;
        ranr_collection_status <- ranr_gui_bridge("prepare");
    }
    action ranr_build_gui_calibration {
        ranr_collection_status <- ranr_gui_bridge("build");
        write ranr_collection_status;
    }
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
    action ranr_configure_vehicle(vehicle v,int stable_id,string kind,bool inbound) {
        v.mobility_id <- stable_id; v.ranr_vehicle_kind <- kind; v.ranr_inbound <- inbound;
        v.day_start <- 5.0+2.0*ranr_uniform(710,stable_id,0);
        v.day_end <- 20.0+4.0*ranr_uniform(710,stable_id,1);
        v.is_work_car <- !inbound and kind!="taxi" and ranr_uniform(711,stable_id,0)>=0.3;
        v.is_entertainment_car <- !inbound and kind!="taxi" and !v.is_work_car;
        if kind!="car" {
            elecar ev <- elecar(v);
            ev.battery_level <- float(ranr_environment["initial_soc_low"])+(float(ranr_environment["initial_soc_high"])-float(ranr_environment["initial_soc_low"]))*ranr_uniform(712,stable_id,0);
            ev.ranr_max_kw <- [60.0,120.0,250.0][int(3.0*ranr_uniform(713,stable_id,0))];
        }
        ranr_vehicle_by_id[stable_id] <- v; ranr_planned_kinds[stable_id] <- kind;
    }
    action ranr_plan_opportunity(int vehicle_id,string kind,float at,string cause) {
        int key <- length(ranr_opportunities)+1;
        ranr_opportunities << ["key"::key,"vehicle_id"::vehicle_id,"kind"::kind,"at"::at,"cause"::cause];
    }
    action ranr_plan_vehicle_opportunities(int vehicle_id,string kind,float start_at,float end_at) {
        if kind="car" or end_at<=start_at { return nil; }
        list<float> weights <- kind="private" ? ranr_private_hours : ranr_taxi_hours;
        float frequency <- kind="private" ? ranr_private_frequency : ranr_taxi_frequency;
        frequency <- frequency*(ranr_case="high" ? 1.8 : 1.0);
        assert length(weights)=24 and sum(weights)>0.0 and min(weights)>=0.0;
        int last_day <- int(ceil((initial_hour*60.0+end_at)/1440.0));
        loop day from: 0 to: last_day {
            float mass <- 0.0; int event_index <- 0;
            loop while: frequency>0.0 {
                mass <- mass-ln(ranr_uniform(720,vehicle_id,day*10000+event_index*3));
                if mass>=frequency { break; }
                float draw <- ranr_uniform(721,vehicle_id,day*10000+event_index*3+1)*sum(weights);
                float cumulative <- 0.0; int hour <- 23;
                loop h from: 0 to: 23 { cumulative <- cumulative+weights[h]; if draw<cumulative { hour <- h; break; } }
                float at <- day*1440.0+hour*60.0+60.0*ranr_uniform(722,vehicle_id,day*10000+event_index*3+2)-initial_hour*60.0;
                if at>=start_at and at<end_at { do ranr_plan_opportunity(vehicle_id,kind,at,"scheduled"); }
                event_index <- event_index+1;
            }
        }
    }
    action ranr_plan_burst(float at,int count) {
        list<int> ids <- list(ranr_vehicle_by_id.keys) where (ranr_vehicle_by_id[each].ranr_vehicle_kind!="car");
        loop entry over: ranr_inbound_plan where (float(each["at"])<=at and float(each["depart"])>at and each["kind"]!="car") { ids << int(entry["id"]); }
        ids <- ids sort_by ranr_uniform(733,each,int(at));
        loop slot from: 0 to: count-1 {
            if count=0 { break; }
            int id <- slot<length(ids) ? ids[slot] : -1;
            string kind <- id in ranr_planned_kinds.keys ? ranr_planned_kinds[id] : "absent";
            do ranr_plan_opportunity(id,kind,at,"burst");
        }
    }
    action ranr_initialize_fleet {
        int n <- 0;
        loop v over: list(car) { do ranr_configure_vehicle(v,1000+n,"car",false); n <- n+1; }
        n <- 0; loop v over: list(private_ev) { do ranr_configure_vehicle(v,10000+n,"private",false); n <- n+1; }
        n <- 0; loop v over: list(taxi_ev) { do ranr_configure_vehicle(v,20000+n,"taxi",false); n <- n+1; }
        assert length(ranr_city_vehicles)=cars+privates+taxis;
        do ranr_validate_gateways;
        float end_at <- ranr_warmup+ranr_measure;
        loop v over: ranr_city_vehicles { do ranr_plan_vehicle_opportunities(v.mobility_id,v.ranr_vehicle_kind,0.0,end_at); }
        float traffic_end <- end_at+ranr_deadline;
        int last_day <- int(ceil((initial_hour*60.0+traffic_end)/1440.0));
        if have_rush {
            loop day from: 0 to: last_day {
                loop window from: 0 to: 1 {
                    list<list<float>> windows <- ranr_environment["rush_windows_hours"];
                    float start_at <- day*1440.0+windows[window][0]*60.0-initial_hour*60.0;
                    float close_at <- day*1440.0+windows[window][1]*60.0-initial_hour*60.0;
                    if close_at<=0.0 or start_at>=traffic_end { continue; }
                    loop kind_index from: 0 to: 2 {
                        string kind <- ["car","private","taxi"][kind_index];
                        int cap <- int(floor([cars,privates,taxis][kind_index]*rush_extra_percent/100.0));
                        if cap=0 { continue; }
                        loop slot from: 0 to: cap-1 {
                            int id <- 1000000+day*1000000+window*100000+kind_index*20000+slot;
                            float at <- start_at+(close_at-start_at)*(slot+ranr_uniform(730,id,0))/cap;
                            if at<0.0 or at>=traffic_end { continue; }
                            int gate <- int(length(ranr_gateways)*ranr_uniform(731,id,0));
                            float depart <- close_at+float(ranr_environment["inbound_dwell_minutes"])*ranr_uniform(732,id,0);
                            ranr_planned_kinds[id] <- kind;
                            ranr_inbound_plan << ["id"::id,"kind"::kind,"at"::at,"depart"::depart,"gateway"::gate];
                            do ranr_plan_vehicle_opportunities(id,kind,at,min(depart,end_at));
                        }
                    }
                }
            }
        }
        if ranr_case in ["burst","combined"] {
            loop day from: 0 to: int(ceil(ranr_measure/1440.0)) {
                loop offset over: [60.0,120.0] {
                    float at <- ranr_warmup+day*1440.0+offset;
                    if at>=end_at { continue; }
                    do ranr_plan_burst(at,ranr_burst_size);
                }
            }
        }
        ranr_opportunities <- ranr_opportunities sort_by float(each["at"]);
        ranr_inbound_plan <- ranr_inbound_plan sort_by float(each["at"]);
        save ranr_opportunities to:ranr_output+"/opportunities.json" format:"json";
        save ranr_inbound_plan to:ranr_output+"/traffic_plan.json" format:"json";
        save "key,vehicle_id,kind,at,cause,status,soc\n" to:ranr_output+"/opportunity_results.csv" format:"text";
        save "at,vehicle_id,kind,event,gateway,x,y,soc\n" to:ranr_output+"/traffic.csv" format:"text";
        save "at,vehicle_id,kind,inbound,state,session,soc,total_metres,total_charged_kwh\n" to:ranr_output+"/vehicles.csv" format:"text";
        save (ranr_city_vehicles collect ["id"::each.mobility_id,"kind"::each.ranr_vehicle_kind,"soc"::(each.is_ev ? elecar(each).battery_level : -1.0),"x"::each.location.x,"y"::each.location.y])
            to:ranr_output+"/initial_fleet.json" format:"json";
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
        float saved_seed <- seed; int saved_usage <- rng_usage;
        seed <- mobility_rng_seed(id,-1);
        vehicle v <- nil;
        if kind="car" { create car with:[location::origin.location,home::central_target] { v <- self; } }
        else if kind="private" { create private_ev with:[location::origin.location,home::central_target,all_stations::list(charging_station)] { v <- self; } }
        else { create taxi_ev with:[location::origin.location,home::central_target,all_stations::list(charging_station)] { v <- self; } }
        seed <- saved_seed; rng_usage <- saved_usage;
        do ranr_configure_vehicle(v,id,kind,true);
        v.ranr_exit_id <- gate; v.ranr_depart_at <- float(entry["depart"]); v.target <- central_target;
        ask v { do compute_path graph:road_network target:central_target.closest_intersection; }
        ranr_inbound_created <- ranr_inbound_created+1;
        ranr_traffic_buffer <- ranr_traffic_buffer+time/60.0+","+id+","+kind+",entered,"+gate+","+v.location.x+","+v.location.y+","+(v.is_ev ? elecar(v).battery_level : -1.0)+"\n";
    }
    string ranr_eligibility(vehicle v) {
        if v=nil or dead(v) { return "absent"; }
        if v.ranr_vehicle_kind="car" { return "not_ev"; }
        if v.ranr_stranded { return "stranded"; }
        if v.ranr_exiting { return "departing"; }
        elecar ev <- elecar(v);
        if ev.needs_charging or ev.is_charging or ev.session_state in ["requested","en_route","waiting","charging"] { return "busy"; }
        if ev.battery_level>=ranr_soc_threshold { return "soc_not_low"; }
        if ev.battery_level<=0.0 { return "stranded"; }
        return "activated";
    }
    action ranr_fleet_tick(float at) {
        loop while: ranr_inbound_cursor<length(ranr_inbound_plan) and float(ranr_inbound_plan[ranr_inbound_cursor]["at"])<=at {
            do ranr_spawn_inbound(ranr_inbound_plan[ranr_inbound_cursor]); ranr_inbound_cursor <- ranr_inbound_cursor+1;
        }
        loop v over: copy(ranr_city_vehicles) where (each.ranr_inbound and !each.ranr_stranded and !each.needs_charging and !each.is_charging and each.final_target=nil and at>=each.ranr_depart_at) {
            intersection exit_node <- ranr_gateways[v.ranr_exit_id];
            if v.ranr_exiting and v.location distance_to exit_node.location<2.0 {
                ranr_traffic_buffer <- ranr_traffic_buffer+at+","+v.mobility_id+","+v.ranr_vehicle_kind+",exited,"+v.ranr_exit_id+","+v.location.x+","+v.location.y+","+(v.is_ev ? elecar(v).battery_level : -1.0)+"\n";
                remove key:v.mobility_id from:ranr_vehicle_by_id;
                ask v { do unregister; do die; } ranr_inbound_exited <- ranr_inbound_exited+1;
            } else {
                v.ranr_exiting <- true;
                ask v { do compute_path graph:road_network target:exit_node; }
            }
        }
        loop while: ranr_opportunity_cursor<length(ranr_opportunities) and float(ranr_opportunities[ranr_opportunity_cursor]["at"])<=at {
            map<string,unknown> opportunity <- ranr_opportunities[ranr_opportunity_cursor]; ranr_opportunity_cursor <- ranr_opportunity_cursor+1;
            int id <- int(opportunity["vehicle_id"]); vehicle v <- ranr_vehicle_by_id[id];
            string status <- ranr_eligibility(v); float soc <- v=nil ? -1.0 : elecar(v).battery_level;
            ranr_opportunity_count <- ranr_opportunity_count+1;
            map<string,unknown> entry <- ranr_record(opportunity); entry["status"] <- status; entry["soc"] <- soc;
            entry["measured"] <- float(opportunity["at"])>=ranr_warmup and float(opportunity["at"])<ranr_warmup+ranr_measure;
            ranr_opportunity_ledger << entry;
            if status="activated" {
                elecar ev <- elecar(v);
                ev.ranr_demand_key <- int(opportunity["key"]); ev.ranr_participating <- true; ev.ranr_measured <- bool(entry["measured"]);
                ev.requested_energy <- max(0.0,(target_soc-ev.battery_level)*battery_capacity_kwh/100.0);
                ask ev { do begin_request; }
                ranr_activated_count <- ranr_activated_count+1;
            } else if opportunity["cause"]="burst" { ranr_burst_shortfall <- ranr_burst_shortfall+1; }
            ranr_opportunity_buffer <- ranr_opportunity_buffer+opportunity["key"]+","+id+","+opportunity["kind"]+","+opportunity["at"]+","+opportunity["cause"]+","+status+","+soc+"\n";
        }
        if at>=ranr_next_vehicle_log {
            assert length(ranr_city_vehicles where (!each.ranr_inbound))=cars+privates+taxis;
            loop v over: ranr_city_vehicles {
                string state <- v.ranr_stranded ? "stranded" : (v.final_target=nil ? "parked" : "driving");
                ranr_vehicle_buffer <- ranr_vehicle_buffer+at+","+v.mobility_id+","+v.ranr_vehicle_kind+","+v.ranr_inbound+","+state+","+
                    (v.is_ev ? elecar(v).session_state : "none")+","+(v.is_ev ? elecar(v).battery_level : -1.0)+","+v.ranr_lifetime_metres+","+v.ranr_lifetime_charged_kwh+"\n";
            }
            ranr_next_vehicle_log <- at+60.0;
        }
    }
    action ranr_flush_fleet {
        if ranr_opportunity_buffer!="" { save ranr_opportunity_buffer to:ranr_output+"/opportunity_results.csv" format:"text" rewrite:false; ranr_opportunity_buffer <- ""; }
        if ranr_traffic_buffer!="" { save ranr_traffic_buffer to:ranr_output+"/traffic.csv" format:"text" rewrite:false; ranr_traffic_buffer <- ""; }
        if ranr_vehicle_buffer!="" { save ranr_vehicle_buffer to:ranr_output+"/vehicles.csv" format:"text" rewrite:false; ranr_vehicle_buffer <- ""; }
    }
}
