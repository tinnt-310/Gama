import csv
import tempfile
import unittest
from pathlib import Path

from verification.events import event_metrics


class EventMetricsTests(unittest.TestCase):
    def fixture(self, extra=(), etas=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        prefix = Path(tmp.name) / "run"
        fields = ["request_id", "event", "time_min", "waiting_min", "eta_min"]
        rows = [dict(request_id="a", event=e, time_min=t, waiting_min=w)
                for e, t, w in [("request",0,0),("assigned",1,0),("arrival",3,0),
                                ("service_started",3,0),("service_completed",5,0)]]
        rows += [dict(request_id="b", event=e, time_min=t, waiting_min=w)
                 for e, t, w in [("request",0,0),("assigned",1,0),("arrival",2,0),("service_started",6,4)]]
        rows += [dict(request_id="c",event="request",time_min=0,waiting_min=0),
                 dict(request_id="c",event="deferred",time_min=1,waiting_min=0)]
        for row in rows:
            if row["event"] == "assigned" and etas is not None:
                row["eta_min"] = etas[row["request_id"]]
        with Path(str(prefix)+"_events.csv").open("w") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader(); writer.writerows(rows + list(extra))
        return prefix

    def test_zero_wait_and_unfinished_cohort(self):
        result = event_metrics(self.fixture())
        self.assertEqual(result["zero_wait_sessions"],1)
        self.assertEqual(result["mean_wait_min"],2)
        self.assertEqual(result["mean_total_min"],3.5)
        self.assertEqual(result["total_sessions"],2)
        self.assertEqual(result["unfinished"],2)
        self.assertEqual(result["unstarted"],1)
        self.assertEqual(result["completed"],1)

    def test_duplicate_arrival_rejected(self):
        prefix = self.fixture([dict(request_id="a",event="arrival",time_min=3,waiting_min=0)])
        with self.assertRaises(ValueError): event_metrics(prefix)

    def test_eta_error_is_separate_from_waiting(self):
        result = event_metrics(self.fixture(etas={"a":2.5,"b":3.0}))
        self.assertEqual(result["eta_sessions"],2)
        self.assertEqual(result["eta_bias_min"],-.25)
        self.assertEqual(result["eta_mae_min"],.75)
        self.assertEqual(result["mean_wait_min"],2)

    def test_negative_wait_rejected(self):
        prefix = self.fixture([dict(request_id="c",event="arrival",time_min=3,waiting_min=0),
                               dict(request_id="c",event="service_started",time_min=2,waiting_min=-1)])
        with self.assertRaises(ValueError): event_metrics(prefix)
