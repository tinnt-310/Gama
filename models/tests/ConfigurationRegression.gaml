model unified_configuration_regression
import "RanrFleetTests.gaml"
global {
    reflex verify_derived_total when: cycle=3 {
        assert elecars=privates+taxis;
        assert length(ranr_city_vehicles)=cars+privates+taxis;
        write "CONFIGURATION_REGRESSION_PASS";
    }
}
experiment "configuration" type:gui parent:"unified_fleet_test";
