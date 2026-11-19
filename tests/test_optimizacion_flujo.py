import sys,threading,unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import pipeline_completo as pipeline
from typeo_core import write_json,TypeoError
class WorkflowOptimizations(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix="optimizacion_");self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
  for d in ['scripts','02_TRABAJO_PSD','job','01_RAW']:(self.base/d).mkdir()
  for f in ['typeo_ps.jsx','pipeline_ps.jsx']:(self.base/'scripts'/f).write_text('// fixture')
  self.job={'job_id':'test','folder':str(self.base/'job'),'opened':str(self.base/'job/opened.json'),'pages':[],'output':str(self.base/'FINAL'),'native_status':str(self.base/'job/native.json'),'cancel':str(self.base/'job/cancel.txt')}
 def test_monitor_starts_before_dispatch_and_stops_after_completion(self):
  write_json(self.job['native_status'],{'job_id':'test','status':'complete'})
  order=[]
  with patch('auto_ok_photoshop.PhotoshopAutoDismisser') as cls,patch('pipeline_completo.threading.Thread'),patch('pipeline_completo.subprocess.Popen') as launch,patch('pipeline_completo.finish_run',return_value={'ok':True}):
   cls.return_value.start.side_effect=lambda:order.append('monitor')
   launch.side_effect=lambda *args:order.append('launch')
   self.assertEqual(pipeline.run(self.job,base=self.base),{'ok':True})
   cls.return_value.stop.assert_called_once()
  self.assertEqual(order,['monitor','launch'])
  self.assertFalse((self.base/'02_TRABAJO_PSD/.typeo_photoshop.lock').exists())
 def test_launch_failure_stops_monitor_and_releases_lock(self):
  with patch('auto_ok_photoshop.PhotoshopAutoDismisser') as cls,patch('pipeline_completo.threading.Thread'),patch('pipeline_completo.subprocess.Popen',side_effect=OSError('No Photoshop')):
   with self.assertRaises(OSError):pipeline.run(self.job,base=self.base)
   cls.return_value.stop.assert_called_once()
  self.assertFalse((self.base/'02_TRABAJO_PSD/.typeo_photoshop.lock').exists())
 def test_selecting_one_page_does_not_open_invalid_unselected_image(self):
  from PIL import Image
  Image.new('RGB',(30,30),'white').save(self.base/'01_RAW/01.png')
  (self.base/'01_RAW/02.png').write_bytes(b'not an image')
  job=pipeline.prepare_run(self.base/'missing',self.base/'FINAL',base=self.base,auto_geometry=True,selected=['01'])
  self.assertEqual([p['page'] for p in job['pages']],['01.png'])
 def test_stale_open_signal_never_starts_workers(self):
  write_json(self.job['opened'],{'job_id':'other'})
  class Stop:
   def __init__(self):self.calls=0
   def wait(self,delay):self.calls+=1;return self.calls>2
  self.assertFalse(pipeline.wait_opened(self.job,Stop()))
if __name__=='__main__':unittest.main()
