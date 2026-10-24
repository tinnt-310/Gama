"""Mechanical native benchmark derivation; no Python estimator or quantiles."""
from pathlib import Path
import sys
ROOT=Path('/home/tinnt/Gama_Workspace/Nha Trang CSs planning')
LEGACY=ROOT/'operations/mc_checkpoint_20261023'
sys.path.insert(0,str(LEGACY))
from mc_runtime import selected_model


def once(text,old,new):
    if text.count(old)!=1:raise ValueError('Source template changed: '+old)
    return text.replace(old,new,1)


def estimator_source():
    source=(ROOT/'models/ranr/Prediction.gaml').read_text()
    head='    map<string,unknown> ranr_estimate('
    start=source.index(head);opening=source.index('{',start);depth=1;end=opening+1
    while depth:
        if source[end]=='{':depth+=1
        elif source[end]=='}':depth-=1
        end+=1
    return source[start:end]


def chunk_model():
    native=estimator_source()
    native=once(native,'ranr_estimate(','ranr_estimate_chunk(')
    native=once(native,'loop sample from: 0 to: ranr_samples-1 {',
                'loop sample from: sample_begin to: sample_end-1 {')
    native=once(native,'return ["mean"::mean_wait,',
                'return ["sample_waits"::waits,"sample_externalities"::externalities,"mean"::mean_wait,')
    result=selected_model((ROOT/'models/tests/RanrPredictionBenchmark.gaml').read_text(),ROOT)
    result=once(result,'global {','global {\n'+native+'\n    int sample_begin <- 0;\n    int sample_end <- 0;\n    string raw_output <- "";')
    result=once(result,'    init {','    init {\n        assert sample_begin>=0 and sample_end>sample_begin and sample_end<=ranr_samples;\n        assert selected_method!="" and selected_station>=0 and selected_probe>=0;\n        list<map<string,unknown>> raw_rows <- [];')
    result=once(result,'ranr_estimate(snapshot,observation,request);',
        'ranr_estimate_chunk(snapshot,observation,request);\n                    raw_rows << ["method"::method,"station"::sid,"probe"::probe,"sample_begin"::sample_begin,"sample_end"::sample_end,"configured_samples"::ranr_samples,"waits"::estimate["sample_waits"],"externalities"::estimate["sample_externalities"],"queue_calls"::ranr_queue_calls];')
    result=once(result,'        save rows to: probe_output format:"text";',
        '        save rows to: probe_output format:"text";\n        assert length(raw_rows)=1;\n        save raw_rows to:raw_output format:"json";')
    result=once(result,'    parameter "Samples" var:ranr_samples;',
        '    parameter "Samples" var:ranr_samples;\n    parameter "Sample begin" var:sample_begin;\n    parameter "Sample end" var:sample_end;\n    parameter "Raw output" var:raw_output;')
    return result


def aggregation_model():
    return '''model ranr_chunk_native_aggregation
import "'''+str(ROOT/'models/ranr/Policy.gaml')+'''"
global {
    geometry shape <- rectangle(100,100);
    string ranr_project_prefix <- "'''+str(ROOT)+'''/";
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
        string rows <- "method,station,probe,mean,p95,externality,queue_calls\\n";
        rows <- rows+input["method"]+","+input["station"]+","+input["probe"]+","+mean(waits)+","+ranr_quantile(values:waits,probability:0.95)+","+mean(externalities)+","+queue_calls+"\\n";
        save rows to:aggregate_output format:"text";
        write "RANR_NATIVE_AGGREGATION_PASS";
    }
}
experiment "ranr_native_aggregation" type:gui {
    float seed <- 900001.0;
    parameter "Input" var:aggregate_input;
    parameter "Output" var:aggregate_output;
}
'''


def verify(folder):
    for name,content in [('PredictionChunk.gaml',chunk_model()),('NativeAggregate.gaml',aggregation_model())]:
        if (folder/name).read_text()!=content:raise ValueError('Mechanically derived model changed: '+name)


if __name__=='__main__':
    here=Path(__file__).parent
    for name,content in [('PredictionChunk.gaml',chunk_model()),('NativeAggregate.gaml',aggregation_model())]:
        path=here/name
        if path.exists() and path.read_text()!=content:raise SystemExit('Do not overwrite a versioned model')
        path.write_text(content)
    verify(here)
