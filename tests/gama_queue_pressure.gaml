model ranr_queue_pressure_regression
import "../models/ranr/Runtime.gaml"
global {
    string ranr_project_prefix <- "../";
    geometry shape <- rectangle(100,100);
    float step <- 60.0;
    init {
        ranr_done <- true;
        create charging_station with:[location::{0,0},port_60::2] { do ranr_index_ports; }
        charging_station station <- charging_station[0];
        create queue_pressure_ev number:2 with:[location::{0,0},battery_level::50.0,requested_energy::10.0,ranr_max_kw::60.0,session_state::"waiting"];
        station.waiting_queue <- list(queue_pressure_ev);
        ask station { do ranr_measure_pressure; }
        float high_capacity <- station.ranr_pressure;
        assert high_capacity>0.0 and high_capacity<1.0;
        station.ranr_station_limit_kw <- 30.0;
        ask station { do ranr_measure_pressure; }
        assert station.ranr_pressure>high_capacity;
        float limited <- station.ranr_pressure;
        station.ranr_capacity_factor <- 0.5;
        ask station { do ranr_measure_pressure; }
        assert station.ranr_pressure>limited;
        station.ranr_capacity_factor <- 1.0; station.ranr_station_limit_kw <- 120.0;
        ask queue_pressure_ev { ranr_max_kw <- 11.0; }
        ask station { do ranr_measure_pressure; }
        assert station.ranr_pressure>high_capacity;
        station.ranr_operational <- false;
        ask station { do ranr_measure_pressure; }
        assert station.ranr_pressure=1.0 and station.ranr_zero_capacity>0;
        station.waiting_queue <- [];
        ask station { do ranr_measure_pressure; }
        assert station.ranr_pressure=0.0;
        station.ranr_operational <- true;
        // Every port is occupied: capacity must include those busy ports.
        ask queue_pressure_ev { ranr_max_kw <- 60.0; ranr_port_id <- index; session_state <- "charging"; }
        station.charging_vehicles <- list(queue_pressure_ev);
        create queue_pressure_ev with:[location::{0,0},battery_level::50.0,requested_energy::10.0,ranr_max_kw::60.0,session_state::"waiting"];
        station.waiting_queue <- [queue_pressure_ev[2]];
        ask station { do ranr_measure_pressure; }
        assert station.ranr_pressure>0.0 and station.ranr_pressure<1.0;
        // The same allocation kernel is exercised through physical integration.
        station.waiting_queue <- []; station.ranr_station_limit_kw <- 60.0;
        ask station { do ranr_advance_service(10.0); }
        assert abs(queue_pressure_ev[0].delivered_energy-4.5)<1e-8;
        assert abs(queue_pressure_ev[1].delivered_energy-4.5)<1e-8;
        assert abs(station.power_consumed-10.0)<1e-8;
        // Unseen-arrival history must retain late arrivals supported by calibration,
        // independently of the 360-minute service evaluation deadline.
        ranr_eta_factors <- [1.0,10.0];
        ranr_arrival_prior <- [["issuer"::0,"travel"::[60.0],"energy"::10.0,"max_kw"::60.0]];
        do ranr_index_calibration;
        assert ranr_arrival_lookback=600.0;
        map<string,unknown> public_snapshot <- ["sid"::0,"source"::"prior","issued"::0.0,"powers"::[60.0],"release_lo"::[0.0],"release_hi"::[0.0],"queue"::[]];
        map<string,unknown> observation <- station.ranr_observe(1000.0,[public_snapshot]);
        assert list<float>(observation["watermarks"])[0]=400.0;
        write "RANR_QUEUE_PRESSURE_PASS";
    }
}
species queue_pressure_ev parent:elecar;
experiment "ranr_queue_pressure" type:gui;
