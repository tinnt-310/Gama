model ranr_network_tests
import "../ranr/Runtime.gaml"
global {
    geometry shape <- rectangle(100,100);
    init {
        ranr_done <- true; ranr_method <- "RANR-AW"; ranr_delay <- 0.0; ranr_loss <- 0.0; ranr_duplicate_probability <- 1.0;
        create charging_station number:2 with:[port_60::1] { ranr_sid <- index; do ranr_capture(0.0); }
        ranr_stations <- list(charging_station); ranr_tick_epoch <- 1;
        do ranr_broadcast(charging_station[0],0.0);
        do ranr_deliver(0.0);
        assert empty(charging_station[1].ranr_received); // Even zero-delay cannot leak same-tick decisions.
        ranr_tick_epoch <- 2; do ranr_deliver(0.0);
        assert charging_station[1].ranr_received_sequence[0]=1;
        assert charging_station[1].ranr_duplicate_packets=1;
        charging_station[0].ranr_critical <- true;
        do ranr_broadcast(charging_station[0],0.01); assert charging_station[0].ranr_sequence=1;
        do ranr_broadcast(charging_station[0],0.2); assert charging_station[0].ranr_sequence=2;
        assert ranr_event_broadcasts=1;
        ranr_partition_begin <- 1.0; ranr_partition_end <- 5.0;
        charging_station[0].ranr_critical <- true; do ranr_broadcast(charging_station[0],2.0);
        ranr_tick_epoch <- 3; do ranr_deliver(2.0);
        assert charging_station[1].ranr_received_sequence[0]=2;
        charging_station[0].ranr_critical <- true; do ranr_broadcast(charging_station[0],6.0);
        ranr_tick_epoch <- 4; do ranr_deliver(6.0);
        assert charging_station[1].ranr_received_sequence[0]=4;
        int sent <- ranr_message_count; ranr_method <- "No-P2P";
        do ranr_broadcast(charging_station[0],10.0); assert ranr_message_count=sent;
        write "RANR_NETWORK_PASS";
    }
}
experiment "ranr_network" type:gui;
