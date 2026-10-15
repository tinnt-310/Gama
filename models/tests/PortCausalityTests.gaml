model port_causality_tests
import "../Traffic.gaml"

global {
    geometry shape<-rectangle(1000,1000);
    init {
        create intersection with:[location::{100,100}];
        create building with:[location::{100,100},closest_intersection::intersection[0],build_type::1];
        buildings_type_1<-list(building);buildings_type_2<-list(building);buildings_type_3<-list(building);
        create charging_station with:[location::{100,100},port_60::1];
        create private_ev with:[location::{100,100},home::building[0],battery_level::79.98] {current_station<-charging_station[0];do start_charging;}
        ask charging_station[0] {do advance_service;}
        create private_ev with:[location::{100,100},home::building[0],battery_level::79.0] {current_station<-charging_station[0];do start_charging;}
        assert private_ev[1].service_start<0.0;
    }
    reflex verify {
        if cycle=50 {
            assert private_ev[1].service_start>=private_ev[0].service_finish;
            assert charging_station[0].served_customer=2;
            assert charging_station[0].port_60=1;
            write "PORT_CAUSALITY_PASS";
        }
    }
}
experiment "port" type:gui {float seed<-42.0;}
