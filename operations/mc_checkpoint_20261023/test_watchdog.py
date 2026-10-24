import unittest
from watchdog import ActivityTracker

class OwnedActivityTests(unittest.TestCase):
 def test_busy_cpu_is_not_stalled_after_many_hours(self):
  t=ActivityTracker(1200);t.update(1,'a',100,0,0)
  self.assertFalse(t.update(1,'a',200,0,50000)['stalled'])
 def test_idle_without_cpu_or_io_gets_diagnosed(self):
  t=ActivityTracker(1200);t.update(1,'a',100,0,0)
  self.assertTrue(t.update(1,'a',100,0,1201)['stalled'])
 def test_disk_io_is_legitimate_activity(self):
  t=ActivityTracker(1200);t.update(1,'a',100,0,0)
  self.assertFalse(t.update(1,'a',100,50,2000)['stalled'])
 def test_reused_pid_gets_a_fresh_identity(self):
  t=ActivityTracker(1200);t.update(1,'old',100,0,0)
  self.assertFalse(t.update(1,'new',100,0,99999)['stalled'])

if __name__=='__main__':unittest.main()
