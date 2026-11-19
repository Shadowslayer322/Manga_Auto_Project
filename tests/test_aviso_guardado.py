import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from auto_ok_photoshop import PhotoshopAutoDismisser,is_save_data_loss_warning,BM_CLICK
class SaveNoticeTests(unittest.TestCase):
 def test_recognizes_spanish_and_english(self):
  for text in ['El documento no se puede guardar como JPEG sin perder informaci\u00f3n.','This document cannot be saved as JPEG without losing information.','Al guardar se perder\u00e1n algunos datos.']:
   self.assertTrue(is_save_data_loss_warning(text),text)
 def test_other_prompts_are_not_accepted(self):
  for text in ['Guardar los cambios antes de cerrar?','Se perder\u00e1n los cambios sin guardar.','Discard unsaved changes?','Sustituir fuentes?','El archivo ya existe. Reemplazar?']:
   self.assertFalse(is_save_data_loss_warning(text),text)
 def simulate(self,text,button='OK'):
  controls={20:('Static',text,201),30:('Button',button,10),40:('Button','No volver a mostrar',1200)}
  monitor=PhotoshopAutoDismisser(verbose=False)
  with patch('auto_ok_photoshop.win32gui') as gui:
   gui.EnumChildWindows.side_effect=lambda hwnd,cb,arg:[cb(k,arg) for k in controls]
   gui.GetClassName.side_effect=lambda k:controls[k][0]
   gui.GetWindowText.side_effect=lambda k:controls[k][1]
   gui.GetDlgCtrlID.side_effect=lambda k:controls[k][2]
   gui.GetWindowLong.side_effect=lambda k,style:3 if k==40 else 0
   monitor._handle_dialog(1,'Adobe Photoshop')
   calls=gui.SendMessage.call_args_list
   gui.PostMessage.assert_not_called()
  return monitor,calls
 def test_clicks_only_ok_even_with_nonstandard_id(self):
  m,calls=self.simulate('El documento no se puede guardar como JPEG sin perder informacion.')
  self.assertEqual(m.dismissed_count,1)
  self.assertEqual(len(calls),1)
  self.assertEqual(calls[0].args,(30,BM_CLICK,0,0))
 def test_never_uses_first_button_as_fallback(self):
  m,calls=self.simulate('Al guardar se perderan datos.','Cancelar')
  self.assertEqual(m.dismissed_count,0);self.assertFalse(calls)
 def test_no_click_for_unsaved_edits(self):
  m,calls=self.simulate('Se perderan los cambios sin guardar.')
  self.assertEqual(m.dismissed_count,0);self.assertFalse(calls)
if __name__=='__main__':unittest.main()
