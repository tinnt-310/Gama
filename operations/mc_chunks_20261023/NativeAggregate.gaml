model ranr_chunk_native_aggregation
import "/home/tinnt/Gama_Workspace/Nha Trang CSs planning/models/ranr/Policy.gaml"
global {
    geometry shape <- rectangle(100,100);
    string ranr_project_prefix <- "/home/tinnt/Gama_Workspace/Nha Trang CSs planning/";
    string aggregate_input <- "";
    string aggregate_output <- "";
    init {
        map<string,unknown> input <- json_file(aggregate_input).contents;
        int expected <- int(input["samples"]);
        list<float> waits <- []; list<float> externalities <- [];
        int cursor <- 0; int queue_calls <- 0;
        loop chunk over:list<map<string,unknown>>(input["chunks"]) {
            assert int(chunk["sample_begin"])=cursor;
            assert int(chunk["configured_samples"])=expected;
            assert string(chunk["method"])=string(input["method"]) and int(chunk["station"])=int(input["station"]) and int(chunk["probe"])=int(input["probe"]);
            list<float> part_waits <- chunk["waits"];
            list<float> part_externalities <- chunk["externalities"];
            int count <- int(chunk["sample_end"])-int(chunk["sample_begin"]);
            assert count>0 and length(part_waits)=count and length(part_externalities)=count;
            waits <- waits+part_waits; externalities <- externalities+part_externalities;
            cursor <- cursor+count; queue_calls <- queue_calls+int(chunk["queue_calls"]);
        }
        assert expected>0 and cursor=expected and length(waits)=expected;
        string rows <- "method,station,probe,mean,p95,externality,queue_calls\n";
        rows <- rows+input["method"]+","+input["station"]+","+input["probe"]+","+mean(waits)+","+ranr_quantile(values:waits,probability:0.95)+","+mean(externalities)+","+queue_calls+"\n";
        save rows to:aggregate_output format:"text";
        write "RANR_NATIVE_AGGREGATION_PASS";
    }
}
experiment "ranr_native_aggregation" type:gui {
    float seed <- 900001.0;
    parameter "Input" var:aggregate_input;
    parameter "Output" var:aggregate_output;
}
