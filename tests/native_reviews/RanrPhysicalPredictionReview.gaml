model ranr_physical_prediction_review
import "../../models/ChargingService.gaml"
import "../../models/ranr/Policy.gaml"
global {
    geometry shape <- rectangle(100,100);
    float step <- 60.0;
    map<string,unknown> forecast <- [];
    init {
        // Exercise every free policy coefficient through the native function.
        ranr_method <- "RANR-AW";
        loop row from:0 to:3 {
            loop column from:0 to:4 {
                ranr_parameters <- zero_vector(20);
                list<float> state <- zero_vector(5); state[column] <- 1.0;
                list<float> baseline <- ranr_weights(state);
                ranr_parameters[row*5+column] <- 1.0;
                list<float> changed <- ranr_weights(state);
                assert abs(sum(changed)-1.0)<1e-10 and min(changed)>0.0;
                assert changed[row]>baseline[row] and changed[4]<baseline[4];
            }
        }
        ranr_method <- "Fixed-Weights"; ranr_parameters <- [1.0,2.0,3.0,4.0];
        assert ranr_weights([1.0,0.0,0.0,0.0,0.0])=ranr_weights([1.0,1.0,1.0,1.0,1.0]);
        write "RANR_ADAPTIVE_PARAMETER_REVIEW_PASS coefficients=20 reference_row=zero";
        ranr_method <- "RANR-AW"; ranr_parameters <- zero_vector(20); ranr_samples <- 8;
        ranr_assumed_compliance <- 1.0; ranr_assumed_defer <- 0.0;
        ranr_arrival_probability <- 1.0; ranr_eta_factors <- [1.0];
        ranr_sorted_eta <- [1.0]; ranr_release_fractions <- [0.5]; ranr_energy_fractions <- [0.5];
        ranr_response_prior <- []; ranr_prior_rate <- 0.0; ranr_prior_background_rate <- 0.0;
        create charging_station number:2 with:[location::{0,0},port_60::1,ranr_station_limit_kw::60.0];
        loop sid from:0 to:1 {
            create review_prediction_ev with:[location::{0,0},battery_level::30.0,requested_energy::9.0,role::"busy",branch::sid] {
                ranr_demand_key <- 10+sid; ranr_max_kw <- 60.0; do begin_request;
                current_station <- charging_station[sid]; do start_charging;
            }
        }
        ask charging_station[0] { do ranr_capture(0.0); }
        map<string,unknown> snapshot <- ranr_clone_snapshot(charging_station[0].ranr_local_snapshot);
        snapshot["sid"] <- 0; snapshot["issued"] <- 0.0; snapshot["source"] <- "local";
        map<string,unknown> observation <- ["at"::0.0,"snapshots"::[snapshot],"watermarks"::[0.0],"rates"::[0.0],
            "exposure"::[["key"::99,"token"::"future","count"::1,"recommended"::0,"issued"::0.0,"expires"::360.0,
                           "travel"::[5.0],"energy"::9.0,"max_kw"::60.0,"context"::"default"]]];
        map<string,unknown> request <- ["key"::100,"energy"::9.0,"max_kw"::60.0,"travel"::[0.0]];
        forecast <- ranr_estimate(snapshot,observation,request);
        create review_prediction_ev with:[location::{0,0},battery_level::30.0,requested_energy::9.0,role::"probe",branch::0] {
            ranr_demand_key <- 100; ranr_max_kw <- 60.0; do begin_request;
            current_station <- charging_station[0]; do start_charging;
        }
    }
    reflex physical {
        if cycle=5 {
            loop sid from:0 to:1 {
                create review_prediction_ev with:[location::{0,0},battery_level::30.0,requested_energy::9.0,role::"future",branch::sid] {
                    ranr_demand_key <- 200+sid; ranr_max_kw <- 60.0; do begin_request;
                    current_station <- charging_station[sid]; do start_charging;
                }
            }
        }
        ask charging_station { do ranr_advance_service(time/60.0); do process_queue; }
        if cycle=45 {
            review_prediction_ev probe <- first(review_prediction_ev where (each.role="probe"));
            review_prediction_ev inserted <- first(review_prediction_ev where (each.role="future" and each.branch=0));
            review_prediction_ev control <- first(review_prediction_ev where (each.role="future" and each.branch=1));
            assert probe.session_state="completed" and inserted.session_state="completed" and control.session_state="completed";
            float physical_externality <- inserted.waiting_time-control.waiting_time;
            assert abs(float(forecast["mean"])-probe.waiting_time)<1e-7;
            assert abs(float(forecast["p95"])-probe.waiting_time)<1e-7;
            assert abs(float(forecast["externality"])-physical_externality)<1e-7;
            write "RANR_PHYSICAL_PREDICTION_REVIEW_PASS mean="+forecast["mean"]+" p95="+forecast["p95"]+
                  " physical_wait="+probe.waiting_time+" externality="+forecast["externality"]+" physical_externality="+physical_externality;
        }
    }
}
species review_prediction_ev parent:elecar { string role; int branch; }
experiment "physical_prediction_review" type:gui;
