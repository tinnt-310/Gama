model ranr_parameter_tests
global {
    init {
        map<string,unknown> config <- json_file("../../tests/fixtures/gama_parameters.json").contents;
        list<float> loaded_parameters <- config["parameters"];
        assert config["backend"]="GAMA" and config["method"]="RANR-AW";
        assert length(loaded_parameters)=20 and sum(loaded_parameters)=0.0;
        write "RANR_PARAMETER_PASS";
    }
}
experiment "ranr_parameters" type:gui;
