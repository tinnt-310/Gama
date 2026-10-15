model dead_lifecycle_tests
import "../Traffic.gaml"

global {
    geometry shape <- rectangle(1000,1000);
    init {
        create intersection with:[location::{100,100}];
        create building with:[location::{100,100},closest_intersection::intersection[0],build_type::1];
        buildings_type_1<-list(building);buildings_type_2<-list(building);buildings_type_3<-list(building);
        create charging_station with:[location::{100,100},closest_intersection::intersection[0],port_60::1];
        create private_ev number:3 with:[location::{100,100},home::building[0],battery_level::79.0] {
            current_station<-charging_station[0];do start_charging;
        }
        create private_ev with:[location::{500,500},home::building[0],battery_level::79.0] {
            do begin_request;current_station<-charging_station[0];session_state<-"en_route";
            current_station.inbound_work[request_id]<-workload;
            current_station.inbound_eta[request_id]<-10.0;
            current_station.inbound_ev[request_id]<-self;
            current_station.inbound_data[request_id]<-world.session_snapshot(self);
        }
    }
    reflex verify {
        if cycle=2 { ask private_ev[2] {do die;} ask last(private_ev) {do die;} }
        if cycle=5 { ask first(private_ev) {do die;} }
        if cycle=6 {
            ask charging_station {do reconcile_sessions;do reconcile_sessions;}
            write "DEATH6 " + length(charging_station[0].waiting_queue) + "," + length(charging_station[0].charging_vehicles) + "," + length(charging_station[0].inbound_work) + "," + length(session_events where(each["event"]="cancelled"));
            assert empty(charging_station[0].waiting_queue);
            assert length(charging_station[0].charging_vehicles)=1;
            assert length(charging_station[0].inbound_work)=0;
            assert length(session_events where(each["event"]="cancelled"))=3;
        }
        if cycle=80 {
            write "DEATH80 " + charging_station[0].port_60 + "," + charging_station[0].served_customer;
            assert charging_station[0].port_60=1;
            assert charging_station[0].served_customer=1;
            assert length(session_events where(each["event"]="cancelled"))=3;
            write "DEAD_LIFECYCLE_PASS";
        }
    }
}
experiment "death" type:gui {float seed<-42.0;}
