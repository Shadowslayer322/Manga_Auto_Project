# Reglas Estrictas de Control de Photoshop 2025 (C:\Manga_Auto_Project)
1. **PROHIBIDO usar `win32com`, `CoInitialize`, `test.vbs`, `test_ps.py` o matar procesos de Photoshop.**
2. El control de Photoshop se realiza EXCLUSIVAMENTE mediante `Photoshop.exe -r` compilando `scripts\cola_limpieza_ps.jsx` a través de `python C:\Manga_Auto_Project\scripts\ejecutar_todo.py`.
3. Al recibir `/limpiar` o una orden de limpieza, ejecuta directamente `python C:\Manga_Auto_Project\scripts\ejecutar_todo.py` sin realizar exploraciones previas.
