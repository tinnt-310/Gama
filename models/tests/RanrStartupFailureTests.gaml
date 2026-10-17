model ranr_startup_failure_tests
import "../main.gaml"

global {
    bool ranr_collect_gui <- true;
    string ranr_output <- "../../outputs/gama_ranr/startup_failure_fixture";
    string ranr_gui_bridge(string operation) {
        return "CALIBRATION NOT READY: fixture registration failure";
    }
    action ranr_prepare_collection {
        // Exercise the real main init failure branch without creating a production collection.
        file destination <- new_folder(ranr_output); ranr_output <- destination.path;
        ranr_collection_status <- ranr_gui_bridge("prepare");
    }
    reflex verify_failure when:ranr_failed {
        assert ranr_done and !ranr_initialized and ranr_tick_epoch=0;
        assert "fixture registration failure" in ranr_error;
        assert "COLLECTION FAILED" in ranr_collection_status;
        assert length(charging_station)=0 and length(ranr_city_vehicles)=0;
        assert file_exists(ranr_output+"/failure.json") and !file_exists(ranr_output+"/completion.json");
        write "RANR_STARTUP_FAILURE_PASS";
    }
}
experiment "ranr_startup_failure" type:gui parent:"Run me";
