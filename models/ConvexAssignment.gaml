model convex_assignment

// Runtime is GAML only. Python reproduces exported immutable snapshots offline.
global {
    int batch_n <- 0;
    int batch_h <- 4;
    float bin_minutes <- 5.0;
    float d_ref <- 30.0;
    float batch_theta <- 0.25;
    float solver_tau;
    float q_upper;
    int solver_limit <- 20000;
    float solver_gap_tolerance <- 1e-7;
    float solver_residual_tolerance <- 1e-6;
    string solver_status <- "not_run";
    int solver_iterations <- 0;
    float primal_residual;
    float consensus_residual;
    float relaxed_objective;
    float lower_bound;
    float relative_gap;
    float integer_objective;
    float pre_repair_objective;
    int repair_moves <- 0;
    int repair_checks <- 0;
    int repair_fallback_checks <- 0;
    int rounding_steps <- 0;
    int communication_messages <- 0;
    float communication_bytes <- 0.0;
    float solver_runtime_ms <- 0.0;
    int fixture_n <- 10;
    int fixture_m <- 3;
    int fixture_h <- 4;
    int fixture_k <- 3;
    float fixture_theta <- 0.25;
    string fixture_capacity <- "varied";
    int fixture_seed <- 7;
    float fixture_rng <- 7.0;
    float rounding_rng <- 42.0;
    float batch_rounding_state;
    string artifact_prefix <- "../outputs/assignment";

    list<float> zeros(int count) {
        list<float> v <- [];
        loop i from: 0 to: count - 1 { v << 0.0; }
        return v;
    }
    float fixture_uniform {
        float value <- 1664525.0 * fixture_rng + 1013904223.0;
        fixture_rng <- value - floor(value / 4294967296.0) * 4294967296.0;
        return fixture_rng / 4294967296.0;
    }
    float rounding_uniform {
        float value <- 1664525.0 * rounding_rng + 1013904223.0;
        rounding_rng <- value - floor(value / 4294967296.0) * 4294967296.0;
        return rounding_rng / 4294967296.0;
    }
    float prox_entropy(float v) {
        // Proximal domain is x>=0. Raw PDHG iterates need not satisfy the simplex.
        // Only projected xp is used in objective reporting and integer recovery.
        if batch_theta = 0.0 { return max(0.0,v); }
        float lo <- -745.0;
        float hi <- ln(max(1.0,v));
        loop i from: 0 to: 51 {
            float mid <- (lo + hi) / 2.0;
            if exp(mid) + solver_tau * batch_theta * (1.0 + mid) < v { lo <- mid; }
            else { hi <- mid; }
        }
        return exp((lo + hi) / 2.0);
    }
    action clear_snapshot {
        ask assignment_edge { do die; }
        ask assignment_station { do die; }
        communication_messages <- 0;
        communication_bytes <- 0.0;
        repair_moves <- 0;
        repair_checks <- 0;
        repair_fallback_checks <- 0;
        rounding_steps <- 0;
    }
    action create_fixture {
        do clear_snapshot;
        fixture_rng <- float(fixture_seed);
        batch_n <- fixture_n;
        batch_h <- fixture_h;
        batch_theta <- fixture_theta;
        create assignment_station number: fixture_m;
        loop m from: 0 to: fixture_m - 1 { assignment_station[m].sid <- m; }
        loop n from: 0 to: batch_n - 1 {
            float demand <- 2.0 + 13.0 * fixture_uniform();
            loop j from: 0 to: min(fixture_k,fixture_m) - 1 {
                int m <- (n+j) mod fixture_m;
                create assignment_edge with: [n::n, owner::assignment_station[m],
                    hbin::int(float(batch_h) * fixture_uniform()), demand::demand,
                    cost::(1.0 + 7.0 * fixture_uniform()), rid::("fixture_" + n)];
            }
        }
        ask assignment_station {
            capacity <- [];
            inbound <- [];
            float base <- 2.0 + 18.0 * world.fixture_uniform();
            loop h from: 0 to: batch_h - 1 {
                float c <- fixture_capacity = "varied" ? 2.0 + 18.0 * world.fixture_uniform() : base;
                if fixture_capacity = "drop" and h >= 1 and h < 3 { c <- 0.0; }
                if fixture_capacity = "recovery" and h < 2 { c <- 0.0; }
                if fixture_capacity = "heterogeneous" { c <- sid mod 2 = 0 ? 2.0*c : 0.5*c; }
                capacity << c;
                inbound << (4.0 * world.fixture_uniform());
            }
        }
    }
    action prepare_solver {
        assert batch_n > 0 and batch_h > 0 and !empty(assignment_station) and !empty(assignment_edge);
        assert d_ref > 0.0 and bin_minutes > 0.0 and batch_theta >= 0.0 and solver_limit > 0;
        assert solver_residual_tolerance > 0.0 and solver_gap_tolerance > 0.0;
        ask assignment_station {
            assert sid >= 0 and sid < length(assignment_station);
            assert length(capacity) = batch_h and length(inbound) = batch_h;
            assert min(capacity) >= 0.0 and min(inbound) >= 0.0;
        }
        assert length(remove_duplicates(list(assignment_station) collect each.sid)) = length(assignment_station);
        ask assignment_edge {
            assert n >= 0 and n < batch_n and hbin >= 0 and hbin < batch_h and owner != nil;
            assert demand >= 0.0 and cost >= 0.0;
        }
        loop n from: 0 to: batch_n - 1 {
            list<assignment_edge> row <- list(assignment_edge) where (each.n = n);
            assert !empty(row);
            assert length(remove_duplicates(row collect each.owner)) = length(row);
        }
        batch_rounding_state <- rounding_rng;
        q_upper <- (sum(list(assignment_station) collect sum(each.inbound)) + sum(list(assignment_edge) collect each.demand)) / d_ref;
        float norm_sq <- float(length(assignment_station) * (3 * batch_h - 1));
        loop e over: assignment_edge { norm_sq <- norm_sq + 1.0 + 2.0 * (e.demand / d_ref)^2; }
        solver_tau <- 0.99 / sqrt(norm_sq);
        ask assignment_edge {
            candidate_edges <- list(assignment_edge) where (each.n = n);
            x <- 1.0 / length(candidate_edges);
            xbar <- x;
            xp <- x;
            nu <- 0.0;
        }
        ask assignment_station {
            local_edges <- list(assignment_edge) where (each.owner = self);
            q <- world.zeros(batch_h);
            qbar <- copy(q);
            lambda1 <- copy(q);
            lambda2 <- copy(q);
            backlog_profile <- copy(q);
            price_profile <- copy(q);
            component <- sid;
        }
        // Components are defined solely by shared candidates.
        bool repeat <- true;
        loop while: repeat {
            repeat <- false;
            loop e over: assignment_edge {
                int smallest <- min(e.candidate_edges collect each.owner.component);
                if e.owner.component > smallest { e.owner.component <- smallest; repeat <- true; }
            }
        }
    }
    action project_assignment {
        loop n from: 0 to: batch_n - 1 {
            list<assignment_edge> row <- list(assignment_edge) where (each.n = n);
            list<float> u <- reverse((row collect each.x) sort_by each);
            float acc <- 0.0;
            float threshold <- 0.0;
            loop i from: 0 to: length(u) - 1 {
                acc <- acc + u[i];
                if u[i] - (acc - 1.0) / (i + 1.0) > 0.0 { threshold <- (acc - 1.0) / (i + 1.0); }
            }
            ask row { xp <- max(0.0,x - threshold); }
            assert min(row collect each.xp) >= 0.0 and max(row collect each.xp) <= 1.0 + 1e-10;
            assert abs(sum(row collect each.xp)-1.0) <= 1e-8;
        }
    }
    action evaluate_solver {
        do project_assignment;
        primal_residual <- 0.0;
        consensus_residual <- 0.0;
        loop e over: assignment_edge {
            consensus_residual <- max(consensus_residual,max(e.candidate_edges collect abs(each.nu - e.nu)));
        }
        relaxed_objective <- 0.0;
        lower_bound <- 0.0;
        ask assignment_station {
            do solver_metrics;
            do recompute_profile(false);
        }
        loop s over: assignment_station {
            primal_residual <- max(primal_residual,s.local_residual);
            relaxed_objective <- relaxed_objective + s.local_objective;
            lower_bound <- lower_bound + s.local_lower_bound;
        }
        relative_gap <- max(0.0,relaxed_objective - lower_bound) / max(1.0,abs(relaxed_objective));
    }
    action solve_snapshot {
        do prepare_solver;
        solver_status <- "timeout";
        float start <- machine_time;
        loop iteration from: 1 to: solver_limit {
            ask assignment_edge { received_sum <- xbar; }
            ask assignment_station { do broadcast_assignment; }
            ask assignment_station { do update_dual; }
            ask assignment_station { do update_primal; }
            solver_iterations <- iteration;
            if iteration mod 20 = 0 or iteration = solver_limit {
                do evaluate_solver;
                if primal_residual <= solver_residual_tolerance and consensus_residual <= solver_residual_tolerance and relative_gap <= solver_gap_tolerance {
                    solver_status <- "converged";
                    break;
                }
            }
        }
        solver_runtime_ms <- machine_time - start;
    }
    action recover_integer {
        do project_assignment;
        ask assignment_edge { z <- xp; }
        // Only one station per connected component executes rounding/repair.
        ask assignment_station where (each.sid = each.component) { do dependent_rounding; }
        integer_objective <- sum(list(assignment_edge) collect (each.cost * each.z));
        ask assignment_station { do recompute_profile(true); }
        integer_objective <- integer_objective + sum(list(assignment_station) collect each.congestion);
        pre_repair_objective <- integer_objective;
        ask assignment_station where (each.sid = each.component) { do exact_repair; }
        integer_objective <- sum(list(assignment_edge) collect (each.cost * each.z)) + sum(list(assignment_station) collect each.congestion);
        ask assignment_edge { assert z = 0.0 or z = 1.0; }
        loop n from: 0 to: batch_n - 1 {
            assert sum((list(assignment_edge) where (each.n = n)) collect each.z) = 1.0;
        }
        assert integer_objective <= pre_repair_objective + 1e-6;
        assert lower_bound <= integer_objective + 1e-6;
    }
    action export_snapshot {
        string config <- "n,m,h,delta_min,d_ref,theta,solver_limit,residual_tolerance,gap_tolerance,tau,q_upper,fixture_seed,fixture_capacity,initial_rounding_state,final_rounding_state,communication_model,x_prox_domain,assignment_domain\n";
        config <- config + batch_n + "," + length(assignment_station) + "," + batch_h + "," + bin_minutes + "," + d_ref + "," + batch_theta + "," + solver_limit + "," + solver_residual_tolerance + "," + solver_gap_tolerance + "," + solver_tau + "," + q_upper + "," + fixture_seed + "," + fixture_capacity + "," + batch_rounding_state + "," + rounding_rng + ",logical_in_process,nonnegative,simplex\n";
        save config to: artifact_prefix + "_config.csv" format: "text";
        string edges <- "n,station,bin,workload,travel_min,x,raw_x,z\n";
        loop e over: assignment_edge { edges <- edges + e.n + "," + e.owner.sid + "," + e.hbin + "," + e.demand + "," + e.cost + "," + e.xp + "," + e.x + "," + e.z + "\n"; }
        save edges to: artifact_prefix + "_edges.csv" format: "text";
        string mapping <- "station,physical_station,component,workload_unit\n";
        loop s over: assignment_station { mapping <- mapping + s.sid + "," + (s.physical_station = nil ? "fixture_" + s.sid : s.physical_station.name) + "," + s.component + ",equivalent_reference_service_minutes\n"; }
        save mapping to: artifact_prefix + "_station_map.csv" format: "text";
        string bins <- "station,bin,capacity,inbound,backlog,price,workload_unit,price_unit\n";
        loop s over: assignment_station {
            loop h from: 0 to: batch_h - 1 { bins <- bins + s.sid + "," + h + "," + s.capacity[h] + "," + s.inbound[h] + "," + s.backlog_profile[h] + "," + s.price_profile[h] + ",equivalent_reference_service_minutes,minutes_per_reference_service_minute\n"; }
        }
        save bins to: artifact_prefix + "_bins.csv" format: "text";
        string metrics <- "status,iterations,residual,relative_gap,relaxed,LB,pre_repair,UB,repair_moves,repair_checks,fallback_checks,messages,bytes,runtime_ms,theta,delta,d_ref,rounding_steps,consensus_residual,travel_cost_min,congestion_surrogate_min,terminal_backlog_service_min\n";
        metrics <- metrics + solver_status + "," + solver_iterations + "," + primal_residual + "," + relative_gap + "," + relaxed_objective + "," + lower_bound + "," + pre_repair_objective + "," + integer_objective + "," + repair_moves + "," + repair_checks + "," + repair_fallback_checks + "," + communication_messages + "," + communication_bytes + "," + solver_runtime_ms + "," + batch_theta + "," + bin_minutes + "," + d_ref + "," + rounding_steps + "," + consensus_residual + "," + sum(list(assignment_edge) collect (each.cost*each.z)) + "," + sum(list(assignment_station) collect each.congestion) + "," + sum(list(assignment_station) collect last(each.backlog_profile)) + "\n";
        save metrics to: artifact_prefix + "_metrics.csv" format: "text";
    }
}

species assignment_edge schedules: [] {
    int n;
    string rid;
    agent ev_ref;
    assignment_station owner;
    int hbin;
    float demand;
    float cost;
    float travel_metres <- 0.0;
    float x;
    float xp;
    float xbar;
    float nu;
    float received_sum;
    float z;
    list<assignment_edge> candidate_edges;
    int u -> n;
    int v -> batch_n + owner.sid;
}

species assignment_station schedules: [] {
    int sid;
    int component;
    agent physical_station;
    list<assignment_edge> local_edges;
    list<float> capacity;
    list<float> inbound;
    list<float> q;
    list<float> qbar;
    list<float> lambda1;
    list<float> lambda2;
    list<float> backlog_profile;
    list<float> price_profile;
    float congestion;
    float local_residual;
    float local_objective;
    float local_lower_bound;

    action broadcast_assignment {
        loop e over: local_edges {
            // Logical unicast: payload (shared request index, extrapolated x), 16 bytes.
            // No capacity, queue or detailed service state is transmitted.
            ask e.candidate_edges where (each.owner != self) { received_sum <- received_sum + e.xbar; }
            communication_messages <- communication_messages + length(e.candidate_edges) - 1;
            communication_bytes <- communication_bytes + 16.0 * (length(e.candidate_edges) - 1);
        }
    }
    action update_dual {
        list<float> load <- copy(inbound);
        loop e over: local_edges { load[e.hbin] <- load[e.hbin] + e.demand * e.xbar; }
        loop h from: 0 to: batch_h - 1 {
            lambda1[h] <- max(0.0,lambda1[h] + solver_tau * (load[h] / d_ref - qbar[h]));
            lambda2[h] <- max(0.0,lambda2[h] + solver_tau * (load[h] / d_ref + (h > 0 ? qbar[h-1] : 0.0) - qbar[h] - capacity[h] / d_ref));
        }
        ask local_edges { nu <- nu + solver_tau * (received_sum - 1.0); }
    }
    action update_primal {
        loop e over: local_edges {
            float new_x <- world.prox_entropy(e.x - solver_tau * (e.cost + e.nu + e.demand / d_ref * (lambda1[e.hbin] + lambda2[e.hbin])));
            e.xbar <- 2.0 * new_x - e.x;
            e.x <- new_x;
        }
        loop h from: 0 to: batch_h - 1 {
            float new_q <- min(q_upper,max(0.0,q[h] - solver_tau * (bin_minutes - lambda1[h] - lambda2[h] + (h < batch_h - 1 ? lambda2[h+1] : 0.0))));
            qbar[h] <- 2.0 * new_q - q[h];
            q[h] <- new_q;
        }
    }
    action solver_metrics {
        local_residual <- 0.0;
        local_lower_bound <- 0.0;
        list<float> load <- copy(inbound);
        loop e over: local_edges {
            load[e.hbin] <- load[e.hbin] + e.demand * e.x;
            local_residual <- max(local_residual,abs(sum(e.candidate_edges collect each.x) - 1.0));
            float g <- e.cost + e.nu + e.demand / d_ref * (lambda1[e.hbin] + lambda2[e.hbin]);
            float xmin <- batch_theta > 0.0 ? exp(max(-745.0,min(0.0,-1.0 - g / batch_theta))) : (g < 0.0 ? 1.0 : 0.0);
            local_lower_bound <- local_lower_bound + g * xmin + (xmin > 0.0 ? batch_theta * xmin * ln(xmin) : 0.0);
            // Equality constant is counted once per EV.
            if sid = min(e.candidate_edges collect each.owner.sid) { local_lower_bound <- local_lower_bound - e.nu; }
        }
        loop h from: 0 to: batch_h - 1 {
            local_residual <- max(local_residual,max(0.0,load[h] / d_ref - q[h]));
            local_residual <- max(local_residual,max(0.0,load[h] / d_ref + (h > 0 ? q[h-1] : 0.0) - q[h] - capacity[h] / d_ref));
            float gq <- bin_minutes - lambda1[h] - lambda2[h] + (h < batch_h - 1 ? lambda2[h+1] : 0.0);
            local_lower_bound <- local_lower_bound + q_upper * min(0.0,gq) + lambda1[h] * inbound[h] / d_ref - lambda2[h] * (capacity[h] - inbound[h]) / d_ref;
        }
    }
    action recompute_profile(bool integer) {
        list<float> load <- copy(inbound);
        local_objective <- 0.0;
        loop e over: local_edges {
            float xx <- integer ? e.z : e.xp;
            load[e.hbin] <- load[e.hbin] + e.demand * xx;
            local_objective <- local_objective + e.cost * xx + (!integer and xx > 0.0 ? batch_theta * xx * ln(xx) : 0.0);
        }
        backlog_profile <- world.zeros(batch_h);
        loop h from: 0 to: batch_h - 1 { backlog_profile[h] <- load[h] + max(0.0,(h > 0 ? backlog_profile[h-1] : 0.0) - capacity[h]); }
        congestion <- bin_minutes * sum(backlog_profile) / d_ref;
        local_objective <- local_objective + congestion;
        price_profile <- world.zeros(batch_h);
        loop h from: batch_h - 1 to: 0 step: -1 {
            price_profile[h] <- bin_minutes / d_ref + (h < batch_h - 1 and backlog_profile[h] > capacity[h+1] ? price_profile[h+1] : 0.0);
        }
    }
    float relocation_delta(assignment_edge e, float direction) {
        // Exact local difference. Recompute only the affected suffix, no schedule/state disclosure.
        float prev <- e.hbin > 0 ? backlog_profile[e.hbin-1] : 0.0;
        float change <- 0.0;
        loop h from: e.hbin to: batch_h - 1 {
            float load <- inbound[h] + sum((local_edges where (each.hbin = h)) collect (each.demand * each.z));
            if h = e.hbin { load <- load + direction * e.demand; }
            float next <- load + max(0.0,prev - capacity[h]);
            change <- change + bin_minutes * (next - backlog_profile[h]) / d_ref;
            prev <- next;
        }
        return change;
    }
    action dependent_rounding {
        // Gather fractions at the component representative and return final integer decisions.
        // Request/candidate metadata is already shared before this stage.
        int remote <- length(list(assignment_edge) where (each.owner.component = component and each.owner != self));
        communication_messages <- communication_messages + 2 * remote;
        communication_bytes <- communication_bytes + 32.0 * remote;
        list<assignment_edge> edges <- list(assignment_edge) where (each.owner.component = component);
        if empty(edges) { return nil; } // An unused station has no EV decisions to round.
        ask edges { assert z >= 0.0 and z <= 1.0; }
        loop while: !empty(edges where (each.z > 1e-10 and each.z < 1.0 - 1e-10)) {
            list<assignment_edge> fractional <- edges where (each.z > 1e-10 and each.z < 1.0 - 1e-10);
            int fractional_before <- length(fractional);
            // DFS obtains a cycle or a maximal path in the fractional bipartite graph.
            list<int> nodes <- [];
            loop e over: fractional { if !(e.u in nodes) { nodes << e.u; } if !(e.v in nodes) { nodes << e.v; } }
            map<int,int> parent <- [];
            map<int,assignment_edge> parent_edge <- [];
            map<int,int> depth <- [];
            list<int> visited <- [];
            list<assignment_edge> trail <- [];
            loop root over: nodes {
                if !empty(trail) { break; }
                if root in visited { continue; }
                list<int> stack <- [root];
                parent[root] <- -1; depth[root] <- 0;
                loop while: !empty(stack) and empty(trail) {
                    int node <- last(stack);
                    if !(node in visited) { visited << node; }
                    list<assignment_edge> adjacent <- fractional where (each.u = node or each.v = node);
                    bool extended <- false;
                    loop edge over: adjacent {
                        int other <- edge.u = node ? edge.v : edge.u;
                        if other = parent[node] { continue; }
                        if !(other in visited) {
                            parent[other] <- node; parent_edge[other] <- edge; depth[other] <- depth[node] + 1;
                            stack << other; extended <- true; break;
                        } else if other in stack and depth[other] < depth[node] {
                            trail << edge;
                            int cursor <- node;
                            list<int> ancestry <- [];
                            loop while: cursor != other {
                                assert cursor in parent.keys and cursor in parent_edge.keys and !(cursor in ancestry);
                                assert length(ancestry) < length(nodes);
                                ancestry << cursor;
                                trail << parent_edge[cursor]; cursor <- parent[cursor];
                            }
                            assert length(trail) mod 2 = 0;
                            break;
                        }
                    }
                    if !extended { remove index: length(stack) - 1 from: stack; }
                }
            }
            if empty(trail) {
                int leaf <- -1;
                // Nested each is deliberately avoided below; choose a degree-one node explicitly.
                loop node over: nodes { if length(fractional where (each.u = node or each.v = node)) = 1 { leaf <- node; break; } }
                assert leaf >= 0; // A nonempty acyclic component has a leaf.
                int previous <- -1;
                int node <- leaf;
                list<int> path_nodes <- [];
                loop while: node >= 0 {
                    assert !(node in path_nodes) and length(path_nodes) < length(nodes);
                    path_nodes << node;
                    list<assignment_edge> next <- fractional where ((each.u = node or each.v = node) and (each.u = node ? each.v : each.u) != previous);
                    if empty(next) { break; }
                    assignment_edge edge <- next[0];trail << edge;
                    int other <- edge.u = node ? edge.v : edge.u;
                    previous <- node;node <- other;
                }
            }
            assert !empty(trail) and length(remove_duplicates(trail)) = length(trail);
            assert length(trail) <= length(fractional);
            float alpha <- 1.0;
            float beta <- 1.0;
            loop i from: 0 to: length(trail) - 1 {
                alpha <- min(alpha,i mod 2 = 0 ? 1.0 - trail[i].z : trail[i].z);
                beta <- min(beta,i mod 2 = 0 ? trail[i].z : 1.0 - trail[i].z);
            }
            assert alpha > 0.0 and beta > 0.0;
            float change <- world.rounding_uniform() < beta / (alpha + beta) ? alpha : -beta;
            loop i from: 0 to: length(trail) - 1 {
                trail[i].z <- trail[i].z + (i mod 2 = 0 ? change : -change);
                if trail[i].z < 1e-10 { trail[i].z <- 0.0; }
                if trail[i].z > 1.0 - 1e-10 { trail[i].z <- 1.0; }
            }
            assert length(edges where (each.z > 1e-10 and each.z < 1.0 - 1e-10)) < fractional_before;
            rounding_steps <- rounding_steps + 1;
        }
        ask edges { z <- float(round(z)); }
    }
    action exact_repair {
        list<assignment_edge> edges <- list(assignment_edge) where (each.owner.component = component);
        bool improve <- true;
        loop while: improve {
            improve <- false;
            list<assignment_station> remotes <- list(assignment_station) where (each.component = component and each != self);
            communication_messages <- communication_messages + length(remotes);
            communication_bytes <- communication_bytes + length(remotes) * (8.0 + 8.0 * batch_h);
            list<map> moves <- [];
            loop old over: (edges where (each.z = 1.0)) {
                loop next over: old.candidate_edges where (each != old) {
                    float proxy <- next.cost - old.cost + next.demand * next.owner.price_profile[next.hbin] - old.demand * old.owner.price_profile[old.hbin];
                    moves << ["proxy"::proxy,"old"::old,"new"::next];
                }
            }
            moves <- moves sort_by float(each["proxy"]);
            int checked <- 0;
            loop move over: moves {
                assignment_edge old <- assignment_edge(move["old"]);
                assignment_edge next <- assignment_edge(move["new"]);
                float exact <- next.cost - old.cost + old.owner.relocation_delta(old,-1.0) + next.owner.relocation_delta(next,1.0);
                repair_checks <- repair_checks + 1;
                if checked >= 5 { repair_fallback_checks <- repair_fallback_checks + 1; }
                checked <- checked + 1;
                communication_messages <- communication_messages + 4;
                communication_bytes <- communication_bytes + 64.0;
                if exact < -1e-6 {
                    old.z <- 0.0;next.z <- 1.0;
                    ask old.owner { do recompute_profile(true); }
                    ask next.owner { do recompute_profile(true); }
                    repair_moves <- repair_moves + 1;
                    improve <- true;break;
                }
            }
        }
    }
}
