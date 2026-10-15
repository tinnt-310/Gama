model station_forecast_math
import "Mobility.gaml"

global {
    float charge_efficiency <- 0.9;
    string information_mode <- "LIVE_STATION_INFORMATION";
    float observation_bin_minutes <- 5.0;
    int observation_window <- 12;
    int observation_min_bins <- 24;
    int observation_min_sessions <- 20;
    int replay_scenarios <- 20;
    int observation_history_bins <- 576; // 48 hours of synthetic observations.
    int forecast_horizon_bins <- 24;
    float replay_similarity_threshold <- -1.0; // UNCONFIGURED until development calibration.
    string waiting_estimator_mode <- "replay";
    string ood_fallback_mode <- "physical_only";
    string waiting_forecast_mode <- "B3";
    bool neighbor_correction_enabled <- false; // Experimental B4-N only; development runner may disable.
    float ridge_penalty <- 1.0;
    float forecast_feature_scale <- 30.0; // Fixed service-minute scaling, identical at train/predict.
    int ridge_min_samples <- 50;
    float neighbor_delay_minutes <- 0.0;
    int communication_degree <- 3;

    list<float> zero_vector(int count) {
        list<float> result <- [];
        if count > 0 { loop k from: 0 to: count-1 { result << 0.0; } }
        return result;
    }
    list<float> ridge_solution(list<float> matrix_data, list<float> target_data) {
        int p <- length(target_data);
        list<float> a <- copy(matrix_data);
        list<float> b <- copy(target_data);
        loop k from: 0 to: p-1 {
            float pivot <- a[k*p+k]; assert pivot > 1e-12;
            if k+1 < p {
                loop i from: k+1 to: p-1 {
                    float ratio <- a[i*p+k]/pivot;
                    loop j from: k to: p-1 { a[i*p+j] <- a[i*p+j]-ratio*a[k*p+j]; }
                    b[i] <- b[i]-ratio*b[k];
                }
            }
        }
        list<float> weights <- zero_vector(p);
        loop reverse_index from: 0 to: p-1 {
            int i <- p-1-reverse_index; float remainder <- b[i];
            if i+1 < p { loop j from: i+1 to: p-1 { remainder <- remainder-a[i*p+j]*weights[j]; } }
            weights[i] <- remainder/a[i*p+i];
        }
        return weights;
    }
    float discrete_shadow_wait(list<float> rates, list<float> release_times, list<map> arrivals, float eta) {
        if empty(rates) { return -1.0; }
        list<float> free_at <- copy(release_times);
        float tick_min <- step/60.0;
        loop entry over: arrivals sort_by float(each["offset"]) {
            float at <- float(entry["offset"]);
            if at > eta+1e-10 { break; }
            float arrival_tick <- tick_min*ceil(at/tick_min-1e-10);
            int selected <- 0;
            loop i from: 0 to: length(rates)-1 {
                float available_start <- max(free_at[i],arrival_tick);
                float selected_start <- max(free_at[selected],arrival_tick);
                if available_start < selected_start-1e-10 or (abs(available_start-selected_start) <= 1e-10 and rates[i] > rates[selected]) { selected <- i; }
            }
            float begin <- max(free_at[selected],arrival_tick);
            float service_min <- 60.0*float(entry["energy"])/(charge_efficiency*rates[selected]);
            free_at[selected] <- begin + tick_min*max(1.0,ceil(service_min/tick_min-1e-10));
        }
        return max(0.0,min(free_at)-eta);
    }
    list<map> rank_station_options(list<map> options, string normalization, string method, list<float> weights) {
        if empty(options) { return []; }
        assert normalization in ["feasible","pareto"];
        assert method in ["minimax","nearest","eta","weighted_sum","monetary","time_wait"];
        if method in ["weighted_sum","monetary"] {
            assert length(weights) = 4 and min(weights) >= 0.0 and sum(weights) > 0.0;
        }
        list<map> result <- [];
        loop option over: options {
            map item <- copy(option); list<float> values <- list<float>(item["criteria"]);
            assert length(values) = 4 and min(values) >= 0.0;
            bool dominated <- false;
            loop competitor over: options {
                list<float> other <- list<float>(competitor["criteria"]); bool no_worse <- true; bool strictly_better <- false;
                loop j from: 0 to: 3 {
                    float eps <- j = 2 ? 1e-10 : 1e-9;
                    if other[j] > values[j]+eps { no_worse <- false; }
                    if other[j] < values[j]-eps { strictly_better <- true; }
                }
                if no_worse and strictly_better { dominated <- true; break; }
            }
            item["pareto"] <- !dominated; result << item;
        }
        list<map> base <- normalization = "pareto" ? (result where bool(each["pareto"])) : result;
        list<float> lower <- []; list<float> upper <- [];
        loop j from: 0 to: 3 {
            list<float> values <- base collect float(list(each["criteria"])[j]);
            lower << min(values); upper << max(values);
        }
        loop item over: result {
            list<float> values <- list<float>(item["criteria"]); list<float> regrets <- [];
            loop j from: 0 to: 3 {
                float eps <- j = 2 ? 1e-10 : 1e-9;
                regrets << (upper[j]-lower[j] <= eps ? 0.0 : (values[j]-lower[j])/(upper[j]-lower[j]));
            }
            float score <- max(regrets);
            if method = "nearest" { score <- values[1]; }
            if method = "eta" { score <- values[0]; }
            if method = "time_wait" { score <- values[0]+values[3]; }
            if method in ["weighted_sum","monetary"] {
                score <- 0.0;
                loop j from: 0 to: 3 { score <- score+weights[j]*(method = "monetary" ? values[j] : regrets[j]); }
            }
            item["regrets"] <- regrets; item["score"] <- score;
            item["time_wait"] <- values[0]+values[3];
        }
        // B1/B2 operate on every feasible option, the multi-criterion policies on Pareto options.
        list<map> eligible <- method in ["nearest","eta"] ? result : (result where bool(each["pareto"]));
        map best <- eligible[0];
        loop item over: eligible {
            float score <- float(item["score"]); float best_score <- float(best["score"]);
            float tie_value <- method in ["nearest","eta"] ? 0.0 : float(item["time_wait"]);
            float best_tie <- method in ["nearest","eta"] ? 0.0 : float(best["time_wait"]);
            if score < best_score-1e-10 or (abs(score-best_score) <= 1e-10 and
                (tie_value < best_tie-1e-9 or (abs(tie_value-best_tie) <= 1e-9 and int(item["sid"]) < int(best["sid"])))) { best <- item; }
        }
        loop item over: result {
            item["recommended"] <- int(item["sid"]) = int(best["sid"]);
            item["score_method"] <- method;
            item["alternative_rank"] <- -1;
        }
        // Deterministic order of eligible alternatives for explanation, independent of original candidate order.
        list<map> ordered <- copy(eligible);
        ordered <- ordered sort_by int(each["sid"]);
        if !(method in ["nearest","eta"]) { ordered <- ordered sort_by float(each["time_wait"]); }
        ordered <- ordered sort_by float(each["score"]);
        // Use the tolerance-aware selected winner first even for nearly equal raw scores.
        ordered <- [best] + (ordered where (int(each["sid"]) != int(best["sid"])));
        loop k from: 0 to: length(ordered)-1 { ordered[k]["alternative_rank"] <- k+1; }
        return result;
    }

}
