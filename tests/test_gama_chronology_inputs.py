from dataclasses import replace
from pathlib import Path
import json
import tempfile
import unittest

from ranr.gama.headless import RunConfig


class StationTimelineInputs(unittest.TestCase):
    def test_unsorted_timeline_is_rejected_without_rewriting_input(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'events.json'
            original = json.dumps([dict(sid=0, at=.8, factor=0., operational=False),
                                   dict(sid=0, at=.2, factor=1., operational=True)])
            path.write_text(original)
            with self.assertRaisesRegex(ValueError, 'ordered by time'):
                replace(RunConfig(development=True), station_events=str(path))
            self.assertEqual(path.read_text(), original)

    def test_equal_timestamps_preserve_file_order(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'events.json'
            events = [dict(sid=0, at=.5, factor=0., operational=False),
                      dict(sid=0, at=.5, factor=1., operational=True)]
            original = json.dumps(events)
            path.write_text(original)
            self.assertEqual(replace(RunConfig(development=True), station_events=str(path)).station_events, str(path))
            self.assertEqual(path.read_text(), original)

    def test_sorted_and_empty_timelines_are_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'events.json'
            for events in ([], [dict(sid=0, at=.2, factor=1., operational=True),
                               dict(sid=0, at=.8, factor=0., operational=False)]):
                path.write_text(json.dumps(events))
                replace(RunConfig(development=True), station_events=str(path))


if __name__ == '__main__':
    unittest.main()
