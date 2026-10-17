model ranr_lookup_tests

global {
    map<string,int> history <- [];
    init {
        loop i from:0 to:20000 { history[string(i)] <- i; }
        list<string> before <- history.keys;
        loop key over:["0","1","10000","20000","missing"] {
            assert (history contains_key key)=(key in history.keys);
        }
        // A nil value is still a present key: direct lookup must preserve the
        // old membership semantics, rather than testing whether value != nil.
        map<string,unknown> nullable <- ["nil_value"::nil];
        assert nullable contains_key "nil_value";
        assert (nullable contains_key "nil_value")=("nil_value" in nullable.keys);
        assert !(nullable contains_key "missing");
        float old_started <- machine_time;
        loop i from:0 to:1999 { assert "20000" in history.keys; }
        float old_ms <- machine_time-old_started;
        float direct_started <- machine_time;
        loop i from:0 to:1999 { assert history contains_key "20000"; }
        float direct_ms <- machine_time-direct_started;
        assert history.keys=before and length(history)=20001;
        assert history["20000"]=20000;
        write "RANR_HISTORY_LOOKUP_TIMING old_ms="+old_ms+" direct_ms="+direct_ms;
        write "RANR_HISTORY_LOOKUP_PASS";
    }
}
experiment "ranr_lookup" type:gui {}
