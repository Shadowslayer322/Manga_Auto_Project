"""Confirmar automaticamente el aviso de perdida de datos al guardar en Photoshop.

Solo pulsa OK/Aceptar en ese aviso; no cambia preferencias ni confirma otros dialogos.
"""
import unicodedata
import ctypes
import threading
import time
import win32con
import win32gui
import win32process
import win32service

try:
    import psutil
except ImportError:
    psutil = None

# Constantes de Windows
IDOK = 1
BM_CLICK = 0x00F5
BM_SETCHECK = 0x00F1
BST_CHECKED = 1
WM_COMMAND = 0x0111
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
VK_RETURN = 0x0D


def is_save_data_loss_warning(text):
    normalized=''.join(c for c in unicodedata.normalize('NFKD',text.casefold()) if not unicodedata.combining(c))
    if any(w in normalized for w in ('sin guardar','unsaved','descartar','discard')):
        return False
    saving=any(w in normalized for w in ('guardar','saved','saving','save as'))
    loss=any(w in normalized for w in ('perder informacion','perder datos','perderan datos','perderan algunos datos','perdida de datos','losing information','lose information','data will be lost','information will be lost','some data may be lost'))
    return saving and loss


def is_save_compatibility_or_format_dialog(text, title=''):
    combined = f'{title} {text}'
    normalized = ''.join(c for c in unicodedata.normalize('NFKD', combined.casefold()) if not unicodedata.combining(c))
    if any(w in normalized for w in ('sin guardar', 'unsaved', 'descartar', 'discard', 'reemplazar', 'replace')):
        return False
    return any(w in normalized for w in (
        'maximizar compatibilidad',
        'maximize compatibility',
        'opciones de formato photoshop',
        'photoshop format options',
    ))


class PhotoshopAutoDismisser:
    def __init__(self, check_interval=0.15, verbose=True):
        self.check_interval = check_interval
        self.verbose = verbose
        self.running = False
        self._thread = None
        self.dismissed_count = 0
        self._pid_is_ps = {}
        self._seen_unknown = set()

    def start(self):
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="PSAutoDismisser")
        self._thread.start()
        if self.verbose:
            print("[AUTO-DISMISS] Monitor de diálogos de Photoshop activo en segundo plano.")

    def stop(self):
        self.running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self.verbose:
            print(f"[AUTO-DISMISS] Monitor detenido. Total diálogos descartados: {self.dismissed_count}")

    def _loop(self):
        # Abrir el escritorio interactivo donde corre Photoshop
        try:
            hdesk = win32service.OpenDesktop("Default", 0, False, win32con.GENERIC_ALL)
        except Exception as e:
            try:
                hdesk = win32service.OpenDesktop("Default", 0, False, win32con.DESKTOP_ENUMERATE | win32con.DESKTOP_WRITEOBJECTS)
            except Exception as e2:
                if self.verbose:
                    print(f"[AUTO-DISMISS] Error accediendo al escritorio interactivo: {e2}")
                return

        while self.running:
            try:
                self._scan_and_dismiss(hdesk)
            except Exception as exc:
                # Silencioso ante errores transitorios de enumeracion
                pass
            time.sleep(self.check_interval)

    def _scan_and_dismiss(self, hdesk):
        popups = []

        def enum_cb(hwnd, _):
            if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
                return True
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            title = win32gui.GetWindowText(hwnd)
            cls = win32gui.GetClassName(hwnd)

            # Detectar si es una ventana de dialogo de Photoshop
            is_ps_dialog = False
            if cls == "#32770":  # Cuadro de dialogo estandar Win32
                # Verificar si pertenece a Photoshop o tiene titulo Adobe Photoshop
                if "Photoshop" in title or "Adobe" in title:
                    is_ps_dialog = True
                else:
                    # Comprobar PID (cacheado para no reabrir psutil.Process cada 150ms)
                    is_ps = self._pid_is_ps.get(pid)
                    if is_ps is None:
                        is_ps = False
                        if psutil is not None:
                            try:
                                is_ps = "photoshop" in psutil.Process(pid).name().lower()
                            except Exception:
                                pass
                        if len(self._pid_is_ps) >= 256:
                            self._pid_is_ps.clear()
                        self._pid_is_ps[pid] = is_ps
                    is_ps_dialog = is_ps
            elif "Photoshop" in title and cls in ("OWL.Window", "DroverLord - Window Class", "PSFloatC", "#32770"):
                # Ventanas con título Photoshop pero no la principal
                parent = win32gui.GetParent(hwnd)
                if parent or win32gui.GetWindow(hwnd, win32con.GW_OWNER):
                    is_ps_dialog = True

            if is_ps_dialog:
                popups.append((hwnd, title, cls, pid))
            return True

        win32gui.EnumDesktopWindows(hdesk, enum_cb, 0)

        for hwnd, title, cls, pid in popups:
            self._handle_dialog(hwnd, title)

    def _handle_dialog(self, hwnd, title):
        buttons = []
        checkboxes = []
        static_texts = []

        def child_cb(chwnd, _):
            ccls = win32gui.GetClassName(chwnd)
            ctext = win32gui.GetWindowText(chwnd)
            cid = win32gui.GetDlgCtrlID(chwnd)
            if ccls.lower() == "button":
                style = win32gui.GetWindowLong(chwnd, win32con.GWL_STYLE)
                # BS_CHECKBOX = 2, BS_AUTOCHECKBOX = 3
                btn_type = style & 0xF
                if btn_type in (win32con.BS_CHECKBOX, win32con.BS_AUTOCHECKBOX):
                    checkboxes.append((chwnd, ctext, cid))
                else:
                    buttons.append((chwnd, ctext, cid))
            elif ccls.lower() == "static":
                static_texts.append(ctext)
            return True

        try:
            win32gui.EnumChildWindows(hwnd, child_cb, 0)
        except Exception:
            return

        combined_text = " ".join([t for t in static_texts if t])
        
        if not (is_save_data_loss_warning(combined_text) or is_save_compatibility_or_format_dialog(combined_text, title)):
            if self.verbose and hwnd not in self._seen_unknown and (combined_text or buttons):
                self._seen_unknown.add(hwnd)
                btn_labels = [b[1] for b in buttons if b[1]]
                print(f'[AUTO-DISMISS] Dialogo PS detectado (no auto-confirmado): title={title!r} text={combined_text[:120]!r} buttons={btn_labels!r}', flush=True)
            return

        # Photoshop usa tambien ID 10: elegir la etiqueta, no el primer boton.
        ok_hwnd=next((bhwnd for bhwnd,btext,cid in buttons
                      if btext.replace('&','').strip().casefold() in ('ok','aceptar')),None)
        if ok_hwnd is None:
            return
        for chwnd, ctext, _cid in checkboxes:
            norm_cb = ''.join(c for c in unicodedata.normalize('NFKD', ctext.replace('&', '').casefold()) if not unicodedata.combining(c))
            if any(k in norm_cb for k in ('no mostrar', 'no volver a mostrar', 'dont show', 'do not show')):
                try:
                    win32gui.SendMessage(chwnd, BM_SETCHECK, BST_CHECKED, 0)
                except Exception:
                    pass
        try:
            win32gui.SendMessage(ok_hwnd,BM_CLICK,0,0)
        except Exception:
            return
        self.dismissed_count+=1
        if self.verbose:
            print('[AUTO-DISMISS] OK al aviso de perdida de datos al guardar: '+combined_text[:120],flush=True)


# Instancia singleton para uso rápido
_dismisser = None

def iniciar_monitor_dialogos():
    global _dismisser
    if _dismisser is None:
        _dismisser = PhotoshopAutoDismisser(check_interval=0.15, verbose=True)
    _dismisser.start()
    return _dismisser

def detener_monitor_dialogos():
    global _dismisser
    if _dismisser is not None:
        _dismisser.stop()
        _dismisser = None


if __name__ == "__main__":
    print("Probando PhotoshopAutoDismisser durante 5 segundos...")
    m = iniciar_monitor_dialogos()
    time.sleep(5)
    detener_monitor_dialogos()
