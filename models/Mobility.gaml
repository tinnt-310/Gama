model mobility

global {
    float step <- 1.0 #s;
    bool keyed_driving <- false;
    bool mobility_cache_distances <- true;
    graph road_network;
    float lane_width <- 1.0;
    float vehicle_icon_size_px <- 40.0;
    int batter_insufficient <- 0;
    list<point> lost_car_location <- [];
    int day_counter <- 1;
    float initial_hour <- 0.0;
    float schedule_start_hour <- 0.0;
    // Daily schedules use clock time; sessions and physics retain elapsed seconds.
    float simulation_hour -> schedule_start_hour + time / 3600.0;
    // Elapsed hours are cumulative; only the minute field rolls over at 60.
    string elapsed_clock_hm -> format_elapsed_hm(time);
    string format_elapsed_hm(float elapsed_seconds) {
        int elapsed_minutes <- int(floor(max(0.0,elapsed_seconds)/60.0));
        int elapsed_hours <- int(elapsed_minutes/60);
        int minute_part <- elapsed_minutes mod 60;
        return (elapsed_hours < 10 ? "0" : "") + string(elapsed_hours) + ":" +
            (minute_part < 10 ? "0" : "") + string(minute_part);
    }
    float car_speed <- rnd(50.0,60.0);
    float ele_car_speed <- rnd(40.0,50.0);
    float day_hour <- (day_counter - 1) * 24.0 update: (day_counter - 1) * 24.0;
    bool half <- true;
    list<int> CHARGING_RATES <- [250, 180, 150, 60, 30, 11];

    float mobility_rng_seed(int entity,int event_key) {
        float value <- abs(seed)+entity*1009.0+event_key*9176.0;
        loop k from: 1 to: 4 { value <- value*16807.0+1.0; value <- value-floor(value/2147483647.0)*2147483647.0; }
        return value;
    }
    float keyed_uniform(float master, int domain, int entity, int draw) {
        float modulus <- 2147483647.0;
        float value <- 1.0 + abs(master)-floor(abs(master)/(modulus-1.0))*(modulus-1.0);
        loop part over: [domain,entity,draw] {
            value <- value*48271.0+float(part)+1.0; value <- value-floor(value/modulus)*modulus;
            value <- value*16807.0+1.0; value <- value-floor(value/modulus)*modulus;
        }
        loop mixing from: 1 to: 3 {
            float high <- float(floor(value/32768.0)); float low <- value-high*32768.0;
            float square <- high*high*32768.0; square <- square-floor(square/modulus)*modulus;
            square <- square*32768.0+2.0*high*low*32768.0+low*low;
            value <- square-floor(square/modulus)*modulus;
            value <- value*16807.0+1.0; value <- value-floor(value/modulus)*modulus;
        }
        return max(1e-12,min(1.0-1e-12,value/modulus));
    }
    list<building> buildings_type_1;
    list<building> buildings_type_2;
    list<building> buildings_type_3;

    float road_speed_factor(road link) {
        return link = nil ? 1.0 : (keyed_driving ? max(0.1,min(1.0,1.0-length(link.all_agents)/max(1.0,link.capacity))) : max(0.1,min(1.0,link.speed_coeff)));
    }

    init {
        assert initial_hour >= 0.0 and initial_hour < 24.0;
        schedule_start_hour <- initial_hour;
    }
}

species intersection schedules: [] skills: [intersection_skill] {

    aspect base {
        draw circle(10) color: #green;
    }
}

species road schedules: (keyed_driving ? [] : list(road)) skills: [road_skill] {
    string type;
    bool chargeroad;
    int num_lanes <- 4;
    float capacity;
    int nb_vehicles -> length(all_agents);
    float speed_coeff <- 1.0 min: 0.1 update: 1.0 - (nb_vehicles / capacity);

    init {
        if (!chargeroad){
            capacity <- 1 + (num_lanes * shape.perimeter / 3);
        }
    }

}

species vehicle skills: [driving] {
    int mobility_id <- index;
    bool ranr_inbound <- false;
    bool ranr_stranded <- false;
    bool ranr_exiting <- false;
    int ranr_exit_id <- -1;
    float ranr_depart_at <- -1.0;
    string ranr_vehicle_kind <- "car";
    float ranr_lifetime_metres <- 0.0;
    float ranr_lifetime_charged_kwh <- 0.0;
    float mobility_nominal_speed -> car_speed;
    path mobility_cached_path;
    list<float> mobility_path_suffix <- [];
    string type;
    building target;
    building work_place <- one_of(buildings_type_2);
    point shift_pt <- location;
    bool at_home <- true;
    building temp_target <- nil;
    bool is_ev <- false;
    float day_start <- rnd(5.0 + day_hour, 7.0 + day_hour);
    float day_end <- rnd(20.0 + day_hour, 24.0 + day_hour);
    float taxi_end <- rnd(20.0 + day_hour, 24.0 + day_hour);
    int schedule_day <- day_counter;
    building home <- nil;
    bool day_end_time <- true;
    bool day_start_time <- false;
    bool needs_charging <- false;
    bool is_charging <- false;
    bool is_work_car <- false;
    bool is_entertainment_car <- false;
    bool has_lunch <- false;
    float wait_until <- -1.0;
    bool wait <- false;
    float entertain_time1 <- rnd(8.0 + day_hour, 11.0 + day_hour);
    float entertain_time2 <- rnd(13.0 + day_hour, 17.0 + day_hour);
    float entertain_time3 <- rnd(18.0 + day_hour, 22.0 + day_hour);
    bool eating <- false;
    image_file my_icon;
    float size <- 10.0;

    init {
        mobility_id <- (is_ev ? 10000 : 0)+index;
        proba_respect_priorities <- 0.0;
        proba_respect_stops <- [1.0];
        proba_use_linked_road <- 0.0;
        lane_change_limit <- 2;
        linked_lane_limit <- 0;
        if (home = nil){
            home <- building closest_to self;
        }

    }
    aspect icon {
        // Screen size keeps the original car images visible at city-wide zoom.
        // Convert each axis separately: a wide display can stretch the world.
        float icon_width <- vehicle_icon_size_px * world.shape.width / max(1.0, #display_width);
        float icon_height <- vehicle_icon_size_px * 9.0 / 16.0 * world.shape.height / max(1.0, #display_height);
        draw my_icon size: {icon_width, icon_height};
    }

    bool mobility_flip(float probability,int draw) {
        return keyed_driving ? world.keyed_uniform(seed,701,mobility_id,cycle*31+draw)<probability : flip(probability);
    }
    float mobility_range(float low,float high,int draw) {
        return keyed_driving ? low+(high-low)*world.keyed_uniform(seed,702,mobility_id,cycle*31+draw) : rnd(low,high);
    }
    building mobility_building(list<building> candidates,int draw) {
        if empty(candidates) { return nil; }
        return keyed_driving ? candidates[min(length(candidates)-1,int(world.keyed_uniform(seed,703,mobility_id,cycle*31+draw)*length(candidates)))] : one_of(candidates);
    }
    reflex work_vehicle_behavior when: is_work_car and !ranr_inbound and !ranr_stranded {

        // Morning commute (6h–9h)
        if (day_start_time and target = nil and !needs_charging) {
            target <- work_place; // Workplaces
            do compute_path graph: road_network target: target.closest_intersection;
            wait <- true;
            at_home <- false;
        }

        // Lunch break at 12h
        if (simulation_hour >= day_hour + 12 and simulation_hour < day_hour + 13 and has_lunch = false and !needs_charging) {
            if (mobility_flip(0.5,1)) {
                temp_target <- target;
                target <- keyed_driving ? (buildings_type_3 closest_to self) : one_of(buildings_type_3 closest_to self); // Food/entertainment
                has_lunch <- true;
                wait <- false;

                do compute_path graph: road_network target: target.closest_intersection;
            } else {
                has_lunch <- true;
            }
        }

        // Return from lunch
        if (has_lunch and final_target = nil and temp_target != nil and !needs_charging) {
            target <- temp_target;
            temp_target <- nil;
            do  compute_path graph: road_network target: target.closest_intersection;
        }

        if (wait_until >= 0 and simulation_hour >= wait_until and !needs_charging) {
            has_lunch <- false;
            target <- home;
            at_home <- true;
            wait_until <- -1.0;
            do compute_path graph: road_network target: target.closest_intersection;

        }

        // End of day
        if (day_end_time and final_target = nil and not at_home and !needs_charging) {
            if (mobility_flip(0.5,2)) {
                target <- mobility_building(buildings_type_3,3); // Go eat out
                wait_until <- simulation_hour + mobility_range(0.5,1.0,4);
            } else {
                target <- home; // Go home
                at_home <- true;
                has_lunch <- false;
            }
            do compute_path graph: road_network target: target.closest_intersection;
        }

        if (simulation_hour > day_hour + 23.5) {
            target <- nil;
        }

    }

    reflex entertainment_behavior when: is_entertainment_car and !ranr_inbound and !ranr_stranded {

        // Only act if not already going somewhere
        if (final_target = nil and wait_until < simulation_hour and !needs_charging) {
            // Time windows: morning, afternoon, evening
            if ((simulation_hour >= entertain_time1 and simulation_hour <= entertain_time1 + step/3600.0 ) or
            (simulation_hour >= entertain_time2 and simulation_hour < day_hour + 17.0 and not eating) or
            (simulation_hour >= entertain_time3 and simulation_hour <= entertain_time3 + step/3600.0)) {

                if (mobility_flip(0.5,5)) {
                    target <- mobility_building(buildings_type_3,6);
                    do compute_path graph: road_network target: target.closest_intersection;
                    wait_until <- simulation_hour + mobility_range(1.0,3.0,7); // wait 1–3 hours
                }

                // Lunchtime
            } else if (simulation_hour >= day_hour + 12 and simulation_hour < day_hour + 13) {
                if (mobility_flip(0.5,8)) {
                    target <- keyed_driving ? (buildings_type_3 closest_to self) : one_of(buildings_type_3 closest_to self); // go out to eat
                    do compute_path graph: road_network target: target.closest_intersection;
                    wait_until <- simulation_hour + mobility_range(0.5,1.5,9);
                    eating <- true;
                }
            }
        }
        if (simulation_hour > day_hour + 13) {
            eating <- false;
        }
        // Go home after waiting
        if (wait_until >= 0 and simulation_hour >= wait_until and final_target = nil and !needs_charging) {
            target <- home;
            do compute_path graph: road_network target: home.closest_intersection;
            wait_until <- -1.0;
        }
    }

    action reset_daily_schedule {
        float day_offset <- (day_counter - 1) * 24.0;
        day_start <- keyed_driving ? day_offset+5.0+2.0*world.keyed_uniform(seed,704,mobility_id,day_counter*8+0) : rnd(5.0 + day_offset, 7.0 + day_offset);
        day_end <- keyed_driving ? day_offset+20.0+4.0*world.keyed_uniform(seed,704,mobility_id,day_counter*8+1) : rnd(20.0 + day_offset, 24.0 + day_offset);
        taxi_end <- keyed_driving ? day_offset+20.0+4.0*world.keyed_uniform(seed,704,mobility_id,day_counter*8+2) : rnd(20.0 + day_offset, 24.0 + day_offset);
        entertain_time1 <- keyed_driving ? day_offset+8.0+3.0*world.keyed_uniform(seed,704,mobility_id,day_counter*8+3) : rnd(8.0 + day_offset, 11.0 + day_offset);
        entertain_time2 <- keyed_driving ? day_offset+13.0+4.0*world.keyed_uniform(seed,704,mobility_id,day_counter*8+4) : rnd(13.0 + day_offset, 17.0 + day_offset);
        entertain_time3 <- keyed_driving ? day_offset+18.0+4.0*world.keyed_uniform(seed,704,mobility_id,day_counter*8+5) : rnd(18.0 + day_offset, 22.0 + day_offset);
        day_start_time <- false;
        day_end_time <- true;
        has_lunch <- false;
        eating <- false;
        wait_until <- -1.0;
        schedule_day <- day_counter;
    }
    reflex update_schedule {
        if schedule_day != day_counter { do reset_daily_schedule; }
        if (simulation_hour > day_start and day_start_time = false){
            day_start_time <- true;
            day_end_time <- false;
        }
        if (simulation_hour > day_end and day_end_time = false) {
            day_end_time <- true;
            day_start_time <- false;
        }
    }

    reflex move when: final_target != nil and !ranr_stranded {
        float prior_metres <- remaining_trip_metres();
        max_speed <- (mobility_nominal_speed #km / #h) * world.road_speed_factor(road(current_road));
        float saved_seed <- seed; int saved_usage <- rng_usage;
        if keyed_driving { seed <- world.mobility_rng_seed(mobility_id,cycle); }
        do drive;
        ranr_lifetime_metres <- ranr_lifetime_metres+max(0.0,prior_metres-remaining_trip_metres());
        if keyed_driving { seed <- saved_seed; rng_usage <- saved_usage; }
        if (final_target = nil) {
            do unregister;
        } else {
            shift_pt <- compute_position();
        }

    }

    point compute_position {
        if (current_road != nil) {
            float dist <- (road(current_road).num_lanes - lowest_lane - mean(range(num_lanes_occupied - 1)) - 0.5) * lane_width;
            if violating_oneway {
                dist <- -dist;
            }

            return location + {cos(heading + 90) * dist / 10, sin(heading + 90) * dist / 10};
        } else {
            return {0, 0};
        }

    }

    float remaining_trip_metres {
        if current_path = nil or final_target = nil { return 0.0; }
        // Native driving can cross several curved road segments in a coarse step.
        // Its remaining road length plus the later edges measures the full route.
        float metres <- current_index >= 0 ? max(0.0, distance_to_current_target) : 0.0;
        int first_edge <- max(0,current_index + 1);
        if keyed_driving and mobility_cache_distances {
            int count <- length(current_path.edges);
            if mobility_cached_path!=current_path or length(mobility_path_suffix)!=count+1 {
                mobility_path_suffix <- [];
                loop k from: 0 to: count { mobility_path_suffix << 0.0; }
                if count>0 {
                    loop reverse_index from: 0 to: count-1 {
                        int k <- count-1-reverse_index;
                        mobility_path_suffix[k] <- mobility_path_suffix[k+1]+current_path.edges[k].perimeter;
                    }
                }
                mobility_cached_path <- current_path;
            }
            return metres+(first_edge<=count ? mobility_path_suffix[first_edge] : 0.0);
        }
        if first_edge < length(current_path.edges) {
            loop edge_index from: first_edge to: length(current_path.edges) - 1 {
                metres <- metres + current_path.edges[edge_index].perimeter;
            }
        }
        return metres;
    }

}

species car parent: vehicle {
    float vehicle_length <- rnd(4.0, 5.0) #m;
    int num_lanes_occupied <- 1;
    float max_speed <- car_speed #km / #h;

    image_file my_icon <- image_file("../includes/car.png");

}

species building schedules: [] {
    intersection closest_intersection <- intersection closest_to self.location;
    string type;
    rgb color_outer_building;
    int build_type;
}
