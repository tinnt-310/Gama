model coordination
import "Traffic.gaml"
import "ConvexAssignment.gaml"

global {
    bool coordination_enabled <- true;
    string assignment_policy <- "proposed"; // nearest is the end-to-end infrastructure baseline
    string oracle_backend <- "mock";
    float batch_seconds <- 60.0;
    float reserve_soc <- 5.0;
    int max_candidates <- 3;
    string candidate_mode <- "ALL_FEASIBLE";
    string eta_model <- "snapshot_speed";
    string cost_mode <- "time_only";
    float electricity_price_vnd_kwh <- 3000.0; // Synthetic tariff per battery-delivered kWh.
    float value_of_time_vnd_min <- 500.0; // Synthetic; used only in time_energy mode.
    float horizon_tail_minutes <- 120.0;
    float next_epoch <- 0.0;
    int batch_sequence <- 0;
    float epoch_min;
    list<elecar> current_batch <- [];
    string run_prefix <- "../outputs/run";
    float rounding_seed <- 42.0;
    bool initialized_coordination <- false;
    float next_run_export <- 0.0;
    bool isolate_run_outputs <- false; // Main enables this; synthetic fixtures choose explicit prefixes.
    bool run_output_ready <- false;
    string output_directory <- "";
    string event_output_prefix <- "";
    int exported_event_count <- 0;
    int event_write_calls <- 0;

    action prepare_run_output {
        if run_output_ready { return nil; }
        if isolate_run_outputs {
            file run_directory <- new_folder(run_prefix + "_" + string(machine_time) + "_" + string(int(seed)));
            output_directory <- run_directory.path;
            run_prefix <- output_directory + "/run";
        }
        run_output_ready <- true;
        write "RUN_OUTPUT_PREFIX " + run_prefix;
    }

    int arrival_bin(float absolute_eta) {
        return min(batch_h-1,max(0,int(ceil(max(0.0,absolute_eta-epoch_min)/bin_minutes))-1));
    }
    list<float> route_forecast(elecar ev, charging_station station) {
        if station.closest_intersection = nil or road_network = nil { return [-1.0,-1.0]; }
        float metres <- 0.0;
        float minutes <- 0.0;
        float speed_mps <- max(1e-6,ele_car_speed/3.6);
        // Inbound ETA follows the route already committed, not a newly shortest route.
        if ev.session_state = "en_route" and ev.current_station = station and ev.current_path != nil and ev.final_target = station.closest_intersection {
            metres <- ev.current_index >= 0 ? max(0.0,ev.distance_to_current_target) : 0.0;
            minutes <- metres/(speed_mps*(eta_model = "snapshot_speed" ? road_speed_factor(road(ev.current_road)) : 1.0))/60.0;
            int first_edge <- max(0,ev.current_index+1);
            if first_edge < length(ev.current_path.edges) {
                loop edge_index from: first_edge to: length(ev.current_path.edges)-1 {
                    road link <- road(ev.current_path.edges[edge_index]);
                    metres <- metres + link.shape.perimeter;
                    minutes <- minutes + link.shape.perimeter/(speed_mps*(eta_model = "snapshot_speed" ? road_speed_factor(link) : 1.0))/60.0;
                }
            }
            return [metres,minutes];
        }
        intersection origin <- intersection closest_to ev;
        if origin = nil { return [-1.0,-1.0]; }
        float connector <- ev.location distance_to origin.location;
        float connector_factor <- 1.0;
        if ev.current_road != nil and ev.current_target != nil {
            origin <- intersection(ev.current_target);
            connector <- ev.distance_to_current_target;
            connector_factor <- eta_model = "snapshot_speed" ? road_speed_factor(road(ev.current_road)) : 1.0;
        }
        metres <- connector; minutes <- connector/(speed_mps*connector_factor)/60.0;
        if origin = station.closest_intersection { return [metres,minutes]; }
        path route <- path_between(road_network,origin,station.closest_intersection);
        if route = nil or empty(route.edges) { return [-1.0,-1.0]; }
        loop segment over: route.edges {
            road link <- road(segment);
            metres <- metres + link.shape.perimeter;
            minutes <- minutes + link.shape.perimeter/(speed_mps*(eta_model = "snapshot_speed" ? road_speed_factor(link) : 1.0))/60.0;
        }
        return [metres,minutes];
    }
    float remaining_route(elecar ev, charging_station station) {
        return route_forecast(ev,station)[0];
    }
    action build_candidates(elecar ev) {
        ev.candidates <- [];
        ev.candidate_eta <- [];
        ev.candidate_distance <- [];
        ev.candidate_energy <- []; ev.candidate_requested_energy <- []; ev.candidate_workload <- [];
        ev.nearest_candidate <- nil;
        list<map> feasible <- [];
        loop station over: list(charging_station) sort_by each.index {
            if !station.compatible { continue; }
            if oracle_backend = "fixed_port" and station.installed_port_count = 0 { continue; }
            list<float> forecast <- route_forecast(ev,station);
            float metres <- forecast[0];
            if metres < 0.0 { continue; }
            float available <- ev.battery_level * battery_capacity_kwh / 100.0;
            if available - consumption_kwh_km * metres / 1000.0 < reserve_soc * battery_capacity_kwh / 100.0 { continue; }
            // Current road-speed snapshot is fixed throughout the synchronous solve.
            float minutes <- forecast[1];
            feasible << ["station"::station,"metres"::metres,"eta"::(epoch_min + minutes)];
        }
        // Stable ETA sort preserves the station-ID order for equal costs.
        feasible <- feasible sort_by float(each["eta"]);
        if !empty(feasible) {
            int keep <- candidate_mode = "ALL_FEASIBLE" ? length(feasible) : min(max_candidates,length(feasible));
            loop i from: 0 to: keep - 1 {
                ev.candidates << charging_station(feasible[i]["station"]);
                ev.candidate_eta << float(feasible[i]["eta"]);
                ev.candidate_distance << float(feasible[i]["metres"]);
                float travel_energy <- consumption_kwh_km*float(feasible[i]["metres"])/1000.0;
                float arrival_energy <- ev.battery_level*battery_capacity_kwh/100.0-travel_energy;
                float charge_energy <- charging_goal = "target_soc" ? max(0.0,target_soc*battery_capacity_kwh/100.0-arrival_energy) : ev.requested_energy;
                ev.candidate_energy << travel_energy;
                ev.candidate_requested_energy << charge_energy;
                ev.candidate_workload << 60.0*charge_energy/(reference_efficiency*reference_power_kw);
            }
        }
        if !empty(ev.candidates) {
            list<charging_station> distance_order <- (ev.candidates sort_by each.index) sort_by ev.candidate_distance[ev.candidates index_of each];
            ev.nearest_candidate <- distance_order[0];
        }
        if empty(ev.candidates) {
            if ev.session_state != "deferred" { ev.session_state <- "deferred"; do record_event(ev,"deferred"); }
        }
    }
    action refresh_inbound {
        ask charging_station {
            do reconcile_sessions;
            loop rid over: copy(inbound_work.keys) {
                elecar ev <- inbound_ev[rid];
                if ev = nil or dead(ev) or !(ev.session_state in ["assigned","en_route"]) {
                    do remove_inbound(rid);
                } else {
                    list<float> forecast <- world.route_forecast(ev,self);
                    if forecast[0] < 0.0 { ask ev { do cancel_request("cancelled"); } }
                    else { inbound_eta[rid] <- max(time / 60.0 + forecast[1],ev.station_arrival_due); }
                }
            }
        }
    }
    action initialize_coordination {
        do prepare_run_output;
        assert step > 0.0 and batch_seconds > 0.0 and bin_minutes > 0.0 and d_ref > 0.0;
        assert charge_efficiency > 0.0 and charge_efficiency <= 1.0 and reference_power_kw > 0.0;
        assert reference_efficiency > 0.0 and reference_efficiency <= 1.0;
        assert candidate_mode in ["ALL_FEASIBLE","TOP_K"];
        assert eta_model in ["nominal_speed","snapshot_speed"];
        assert charging_goal in ["fixed_request","target_soc"] and target_soc > 0.0 and target_soc <= 100.0;
        assert cost_mode in ["time_only","time_energy"];
        assert electricity_price_vnd_kwh >= 0.0 and value_of_time_vnd_min > 0.0;
        assert battery_capacity_kwh > 0.0 and consumption_kwh_km >= 0.0 and max_candidates > 0;
        assert ele_car_speed > 0.0 and reserve_soc >= 0.0 and reserve_soc <= 100.0;
        assert horizon_tail_minutes >= 0.0 and mock_capacity_per_bin >= 0.0;
        assert mock_profile in ["constant","drop","recovery","heterogeneous"];
        if service_backend != "fixed_port" { write "Robot integration NOT_IMPLEMENTED"; assert false; }
        if !(oracle_backend in ["mock","fixed_port"]) { write "Robot oracle NOT_IMPLEMENTED"; assert false; }
        rounding_rng <- rounding_seed;
        initialized_coordination <- true;
        do export_config;
    }
    action coordinate_batch {
        assert runtime_mode = "IDEAL_COORDINATED_ASSIGNMENT";
        if !initialized_coordination { do initialize_coordination; }
        epoch_min <- time / 60.0;
        do refresh_inbound;
        list<elecar> pending <- ev_population where (each.session_state in ["requested","deferred"]);
        if empty(pending) { return nil; }
        do clear_snapshot;
        current_batch <- [];
        float max_eta <- epoch_min;
        loop ev over: pending {
            do build_candidates(ev);
            if !empty(ev.candidates) { current_batch << ev; max_eta <- max(max_eta,max(ev.candidate_eta)); }
        }
        if empty(current_batch) { return nil; }
        loop station over: charging_station {
            if !empty(station.inbound_eta) { max_eta <- max(max_eta,max(station.inbound_eta.values)); }
        }
        batch_n <- length(current_batch);
        batch_h <- max(1,int(ceil((max_eta-epoch_min+horizon_tail_minutes)/bin_minutes)));
        list<charging_station> used <- [];
        loop ev over: current_batch { loop station over: ev.candidates { if !(station in used) { used << station; } } }
        // Stable ID order determines component representatives.
        used <- used sort_by each.index;
        loop i from: 0 to: length(used) - 1 {
            charging_station station <- used[i];
            create assignment_station with: [sid::i,physical_station::station] {
                capacity <- oracle_backend = "fixed_port" ? station.forecast_fixed_port(epoch_min,batch_h,bin_minutes) : station.forecast_service(epoch_min,batch_h);
                inbound <- world.zeros(batch_h);
                loop rid over: station.inbound_work.keys {
                    int h <- world.arrival_bin(station.inbound_eta[rid]);
                    inbound[h] <- inbound[h] + station.inbound_work[rid];
                }
            }
        }
        loop n from: 0 to: batch_n - 1 {
            elecar ev <- current_batch[n];
            loop i from: 0 to: length(ev.candidates) - 1 {
                charging_station station <- ev.candidates[i];
                assignment_station block <- first(list(assignment_station) where (each.physical_station = station));
                create assignment_edge with: [n::n,rid::ev.request_id,ev_ref::ev,owner::block,
                    hbin::arrival_bin(ev.candidate_eta[i]),demand::ev.candidate_workload[i],
                    cost::(ev.candidate_eta[i]-epoch_min + (cost_mode = "time_energy" ? electricity_price_vnd_kwh*ev.candidate_energy[i]/value_of_time_vnd_min : 0.0)),travel_metres::ev.candidate_distance[i]];
            }
        }
        list<float> costs <- list(assignment_edge) collect each.cost;
        batch_theta <- 0.05 * max(1.0,median(costs));
        if assignment_policy = "nearest" {
            do prepare_solver;
            loop n from: 0 to: batch_n - 1 {
                list<assignment_edge> row <- ((list(assignment_edge) where (each.n = n)) sort_by each.owner.sid) sort_by each.travel_metres;
                ask row { x <- self = row[0] ? 1.0 : 0.0; }
            }
            do evaluate_solver;
            solver_status <- "baseline_nearest";
            solver_iterations <- 0;
            do project_assignment;
            ask assignment_edge { z <- xp; }
            ask assignment_station { do recompute_profile(true); }
            integer_objective <- sum(list(assignment_station) collect each.local_objective);
            pre_repair_objective <- integer_objective;
        } else {
            assert assignment_policy = "proposed";
            do solve_snapshot;
            do recover_integer;
        }
        batch_sequence <- batch_sequence + 1;
        artifact_prefix <- run_prefix + "_batch_" + batch_sequence;
        do export_snapshot;
        string candidates <- "request_id,ev_id,station,eta_min,travel_min,travel_m,workload_service_min,x,z,nearest,travel_kwh,arrival_kwh,requested_kwh,extra_electricity_vnd,direct_cost_min\n";
        loop edge over: assignment_edge {
            elecar ev <- elecar(edge.ev_ref);
            charging_station station <- charging_station(edge.owner.physical_station);
            int candidate <- ev.candidates index_of station;
            candidates <- candidates + ev.request_id + "," + ev.name + "," + station.name + "," + ev.candidate_eta[candidate] + "," + (ev.candidate_eta[candidate]-epoch_min) + "," + ev.candidate_distance[candidate] + "," + edge.demand + "," + edge.xp + "," + edge.z + "," + (station = ev.nearest_candidate) + "," + ev.candidate_energy[candidate] + "," + (ev.battery_level*battery_capacity_kwh/100.0-ev.candidate_energy[candidate]) + "," + ev.candidate_requested_energy[candidate] + "," + electricity_price_vnd_kwh*ev.candidate_energy[candidate] + "," + edge.cost + "\n";
        }
        save candidates to: artifact_prefix + "_candidates.csv" format: "text";
        do commit_assignment;
        do export_run;
    }
    action commit_assignment {
        // No fractional/initial-rounded workload is ever written to the ledger.
        assert runtime_mode = "IDEAL_COORDINATED_ASSIGNMENT";
        loop edge over: assignment_edge where (each.z = 1.0) {
            elecar ev <- elecar(edge.ev_ref);
            charging_station station <- charging_station(edge.owner.physical_station);
            ev.current_station <- station;
            ev.commit_time <- time / 60.0;
            ev.total_distance <- 0.0;
            int candidate <- ev.candidates index_of station;
            ev.assigned_eta <- ev.candidate_eta[candidate];
            ev.assigned_travel_energy <- ev.candidate_energy[candidate];
            ev.requested_energy <- ev.candidate_requested_energy[candidate];
            ev.workload <- edge.demand;
            ev.session_state <- "assigned";
            do record_event(ev,"assigned");
            station.inbound_work[ev.request_id] <- ev.workload;
            station.inbound_eta[ev.request_id] <- ev.candidate_eta[candidate];
            station.inbound_ev[ev.request_id] <- ev;
            station.inbound_data[ev.request_id] <- session_snapshot(ev);
            ask ev {
                charge_home <- false;
                do compute_path graph: road_network target: current_station.closest_intersection;
                session_state <- "en_route";
                ask world { do record_event(myself,"en_route"); }
                // An EV already at the station needs no travel interval.
                if final_target = nil and location distance_to current_station.closest_intersection.location < 2.0 {
                    do start_charging;
                }
            }
        }
    }
    action export_config {
        string config <- "clock_step_seconds,batch_seconds,bin_minutes,horizon_tail_minutes,d_ref,power_ref_kw,efficiency,battery_kwh,consumption_kwh_km,reserve_soc,max_candidates,policy,oracle,profile,service,rounding_seed,solver_limit,synthetic_ev,forecast_mismatch,start_hour,candidate_mode,reference_efficiency,mobility_seed,workload_unit,forecast_model,eta_model,event_export_mode,charging_goal,target_soc,cost_mode,electricity_price_vnd_kwh,value_of_time_vnd_min,tariff_basis\n";
        config <- config + step + "," + batch_seconds + "," + bin_minutes + "," + horizon_tail_minutes + "," + d_ref + "," + reference_power_kw + "," + charge_efficiency + "," + battery_capacity_kwh + "," + consumption_kwh_km + "," + reserve_soc + "," + max_candidates + "," + assignment_policy + "," + oracle_backend + "," + mock_profile + "," + service_backend + "," + rounding_seed + "," + solver_limit + ",true," + (oracle_backend = "mock") + "," + schedule_start_hour + "," + candidate_mode + "," + reference_efficiency + "," + seed + ",equivalent_reference_service_minutes," + (oracle_backend = "mock" ? "prescribed_capacity" : "fixed_port_fifo_shadow") + "," + eta_model + ",incremental_append," + charging_goal + "," + target_soc + "," + cost_mode + "," + electricity_price_vnd_kwh + "," + value_of_time_vnd_min + ",battery_delivered_kwh\n";
        save config to: run_prefix + "_config.csv" format: "text";
    }
    action export_event_delta {
        if event_output_prefix != run_prefix or !file_exists(run_prefix + "_events.csv") {
            event_output_prefix <- run_prefix; exported_event_count <- 0; event_write_calls <- 0;
            string header <- "request_id,ev_id,event,time_min,station,requested_kwh,delivered_kwh,waiting_min,travel_m,state,commit_min,eta_min,soc_pct,travel_kwh,forecast_travel_kwh,extra_electricity_vnd,choice_wait_min,chosen_forecast_status\n";
            save header to: run_prefix + "_events.csv" format: "text";
            event_write_calls <- event_write_calls + 1;
        }
        assert length(session_events) >= exported_event_count;
        if length(session_events) = exported_event_count { return nil; }
        string events <- "";
        loop event_index from: exported_event_count to: length(session_events)-1 {
            map entry <- session_events[event_index];
            events <- events + entry["request_id"] + "," + entry["ev_id"] + "," + entry["event"] + "," + entry["time_min"] + "," + entry["station"] + "," + entry["requested_kwh"] + "," + entry["energy_kwh"] + "," + entry["waiting_min"] + "," + entry["travel_m"] + "," + entry["state"] + "," + entry["commit_min"] + "," + entry["eta_min"] + "," + entry["soc"] + "," + entry["travel_kwh"] + "," + entry["forecast_travel_kwh"] + "," + (runtime_mode = "IDEAL_COORDINATED_ASSIGNMENT" ? string(float(entry["travel_kwh"])*electricity_price_vnd_kwh) : "") + "," + entry["choice_wait_min"] + "," + entry["chosen_forecast_status"] + "\n";
        }
        save events to: run_prefix + "_events.csv" format: "text" rewrite: false;
        exported_event_count <- length(session_events);
        event_write_calls <- event_write_calls + 1;
    }
    action export_run {
        do export_event_delta;
        string io <- "time_min,event_rows,event_write_calls,event_export_mode\n" + time/60.0 + "," + exported_event_count + "," + event_write_calls + ",incremental_append\n";
        save io to: run_prefix + "_io.csv" format: "text";
        string stations <- "time_min,station,waiting,charging,inbound_requests,inbound_work,started,completed,mean_wait_min,grid_kwh,installed_ports,available_power_kw,access_distance_m\n";
        loop s over: charging_station { stations <- stations + time/60.0 + "," + s.name + "," + length(s.waiting_queue) + "," + length(s.charging_vehicles) + "," + length(s.inbound_work) + "," + sum(s.inbound_work.values) + "," + s.vehicle_charged + "," + s.served_customer + "," + s.get_average_waiting_time() + "," + s.power_consumed + "," + s.installed_port_count + "," + s.available_power_kw + "," + (s.closest_intersection = nil ? 0.0 : s.location distance_to s.closest_intersection.location) + "\n"; }
        save stations to: run_prefix + "_stations.csv" format: "text";
        string status <- "time_min,deferred_events,stranded_events,cancelled_events,unfinished_sessions,unstarted_sessions\n";
        status <- status + time/60.0 + "," + length(session_events where (each["event"] = "deferred")) + "," + length(session_events where (each["event"] = "stranded")) + "," + length(session_events where (each["event"] = "cancelled")) + "," + length(ev_population where (each.needs_charging)) + "," + length(ev_population where (each.needs_charging and each.service_start < 0.0)) + "\n";
        save status to: run_prefix + "_status.csv" format: "text";
    }
    reflex coordination_epoch when: coordination_enabled and runtime_mode = "IDEAL_COORDINATED_ASSIGNMENT" and time >= next_epoch {
        do coordinate_batch;
        next_epoch <- time + batch_seconds;
    }
    reflex export_events when: coordination_enabled and time >= next_run_export {
        do export_run;
        next_run_export <- time + 60.0;
    }
}
