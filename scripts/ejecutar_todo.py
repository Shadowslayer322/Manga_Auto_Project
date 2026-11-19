"""Entrada de Photoshop: typeo integrado y ejecuciones experimentales conservadas."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typeo_core import resolve_photoshop_exe


def main():
    args_unificados=sys.argv[1:]
    legacy=any(a.startswith('--prueba-') or a.startswith('--revision-') or a=='--despachar-typeo' for a in args_unificados)
    if not legacy:
        from pipeline_completo import main as complete_pipeline
        # Las entradas de produccion anteriores ahora tambien ejecutan el flujo completo.
        aliases={'--completo','--typeo','--traducir-typear','--traducir'}
        complete_pipeline([a for a in args_unificados if a not in aliases])
        return
    if '--despachar-typeo' in sys.argv[1:]:
        dispatch=argparse.ArgumentParser(description='Despacho verificado del typeo a Photoshop')
        dispatch.add_argument('--despachar-typeo', required=True)
        dispatch.add_argument('--tiempo-maximo', type=int, default=900)
        args=dispatch.parse_args()
        from typeo_pipeline import dispatch_job
        dispatch_job(args.despachar_typeo, timeout=args.tiempo_maximo)
        return
    for flag in ('--typeo', '--traducir-typear'):
        if flag in sys.argv[1:]:
            from typeo_pipeline import main as integrated_typeo
            remaining=[a for a in sys.argv[1:] if a != flag]
            integrated_typeo((['--traducir'] if flag=='--traducir-typear' else [])+remaining)
            return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prueba-typeo-004', action='store_true')
    parser.add_argument('--prueba-cuadros-004', action='store_true')
    parser.add_argument('--prueba-borde5-004', action='store_true')
    parser.add_argument('--prueba-silueta-004', action='store_true')
    parser.add_argument('--prueba-palabras-004', action='store_true')
    parser.add_argument('--prueba-capas-sueltas-004', action='store_true')
    parser.add_argument('--prueba-typeo-todas', action='store_true')
    parser.add_argument('--revision-typeo-005', action='store_true')
    parser.add_argument('--revision-dos-pasadas', action='store_true')
    parser.add_argument('--revision-final-005', action='store_true')
    parser.add_argument('--revision-paneles', action='store_true')
    parser.add_argument('--reenviar', action='store_true')
    args = parser.parse_args()
    base = Path(__file__).resolve().parents[1]
    if args.revision_paneles:
        exp=base/'07_EXPERIMENTOS_TRADUCCION_TYPEO/prueba_09_paneles'
        cfgs=json.loads((exp/'config_lote.json').read_text(encoding='utf-8'))
        if any(Path(c['output']).exists() for c in cfgs):raise FileExistsError('La revision ya tiene resultados')
        jsx=base/'scripts/cola_limpieza_ps.jsx'
        jsx.write_text((exp/'lote_revision.jsx').read_text(encoding='utf-8'),encoding='utf-8')
        subprocess.run([resolve_photoshop_exe(),'-r',str(jsx)])
        print('Revision de globos y limites de panel enviada a Photoshop.')
        return
    if args.revision_final_005:
        exp=base/'07_EXPERIMENTOS_TRADUCCION_TYPEO/prueba_08_revision'
        cfg=json.loads((exp/'005/config_final.json').read_text(encoding='utf-8'))
        if Path(cfg['output']).exists():raise FileExistsError('La revision final ya existe')
        jsx=base/'scripts/cola_limpieza_ps.jsx'
        jsx.write_text((exp/'revision_final_005.jsx').read_text(encoding='utf-8'),encoding='utf-8')
        subprocess.run([resolve_photoshop_exe(),'-r',str(jsx)])
        print('Revision final de tecnicas enviada a Photoshop.')
        return
    if args.revision_dos_pasadas:
        exp=base/'07_EXPERIMENTOS_TRADUCCION_TYPEO/prueba_08_revision'
        cfgs=json.loads((exp/'config_lote.json').read_text(encoding='utf-8'))
        if any(Path(c['output']).exists() for c in cfgs):raise FileExistsError('La revision ya tiene resultados')
        jsx=base/'scripts/cola_limpieza_ps.jsx'
        jsx.write_text((exp/'lote_revision.jsx').read_text(encoding='utf-8'),encoding='utf-8')
        subprocess.run([resolve_photoshop_exe(),'-r',str(jsx)])
        print('Revision experimental de cinco paginas enviada a Photoshop.')
        return
    if args.revision_typeo_005:
        exp=base/'07_EXPERIMENTOS_TRADUCCION_TYPEO/prueba_07_todas'
        cfg=json.loads((exp/'005/config_final.json').read_text(encoding='utf-8'))
        if Path(cfg['output']).exists():raise FileExistsError('La revision ya existe')
        jsx=base/'scripts/cola_limpieza_ps.jsx'
        jsx.write_text((exp/'revision_005.jsx').read_text(encoding='utf-8'),encoding='utf-8')
        subprocess.run([resolve_photoshop_exe(),'-r',str(jsx)])
        print('Revision experimental de 005 enviada a Photoshop.')
        return
    if args.prueba_typeo_todas:
        exp=base/'07_EXPERIMENTOS_TRADUCCION_TYPEO/prueba_07_todas'
        cfgs=json.loads((exp/'config_lote.json').read_text(encoding='utf-8'))
        if any(Path(c['output']).exists() for c in cfgs):
            raise FileExistsError('Ya existe un resultado del lote; no se sobrescribe')
        jsx=base/'scripts/cola_limpieza_ps.jsx'
        jsx.write_text((exp/'lote_typeo.jsx').read_text(encoding='utf-8'),encoding='utf-8')
        result=subprocess.run([resolve_photoshop_exe(),'-r',str(jsx)])
        print('Lote experimental enviado a Photoshop; comprobar los cinco registros. Estado:',result.returncode)
        return
    if args.prueba_cuadros_004 or args.prueba_borde5_004 or args.prueba_silueta_004 or args.prueba_palabras_004 or args.prueba_capas_sueltas_004:
        exp=base/'07_EXPERIMENTOS_TRADUCCION_TYPEO'/('prueba_06' if args.prueba_capas_sueltas_004 else ('prueba_05' if args.prueba_palabras_004 else ('prueba_04' if args.prueba_silueta_004 else ('prueba_03' if args.prueba_borde5_004 else 'prueba_02'))))
        cfg=json.loads((exp/'config_prueba.json').read_text(encoding='utf-8'))
        if Path(cfg['output']).exists():
            raise FileExistsError('El resultado experimental ya existe')
        jsx=base/'scripts/cola_limpieza_ps.jsx'
        jsx.write_text((exp/'typeo_cuadros.jsx').read_text(encoding='utf-8').replace('__CONFIG__',json.dumps(cfg,ensure_ascii=True)),encoding='utf-8')
        result=subprocess.run([resolve_photoshop_exe(),'-r',str(jsx)])
        print('Prueba de cuadros enviada; comprobar el registro y el PSD. Estado del lanzador:',result.returncode)
        return
    if not args.prueba_typeo_004:
        parser.error('Seleccionar una prueba experimental explicita')
    exp = base/'07_EXPERIMENTOS_TRADUCCION_TYPEO/prueba_01'
    out = exp/'photoshop_004'
    out.mkdir(exist_ok=True)
    output = out/'004_PRUEBA_TYPEO.psd'
    if output.exists():
        raise FileExistsError('El PSD experimental ya existe; no se sobrescribe.')
    if args.reenviar:
        jsx=base/'scripts/cola_limpieza_ps.jsx'
        if not (out/'config_prueba.json').exists() or 'PRUEBA_TYPEO' not in jsx.read_text(encoding='utf-8'):
            raise RuntimeError('No hay una prueba de typeo preparada para reenviar')
        subprocess.run([resolve_photoshop_exe(),'-r',str(jsx)],check=True)
        print('Prueba experimental reenviada a Photoshop.')
        return
    source = base/'02_TRABAJO_PSD/004.psd'
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    copy = out/'004_BASE_COPIA.psd'
    if copy.exists():
        raise FileExistsError('La copia de base ya existe; revisar la prueba anterior.')
    shutil.copy2(source, copy)
    items = [i for i in json.loads((exp/'guion_prueba.json').read_text(encoding='utf-8')) if i['pagina']=='004.jpg']
    cfg = dict(input=copy.as_posix(), output=output.as_posix(),
               preview=(out/'004_PREVIEW_PS.jpg').as_posix(),
               log=(out/'resultado_ps.txt').as_posix(), done=(out/'EXITO.txt').as_posix(),items=items)
    (out/'config_prueba.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'integridad_fuente.json').write_text(json.dumps({'archivo':str(source),'sha256':source_hash},indent=2),encoding='utf-8')
    jsx=base/'scripts/cola_limpieza_ps.jsx'
    # Ruta prescrita por las reglas locales, creada solo si no existia.
    template=(exp/'typeo_ps.jsx').read_text(encoding='utf-8')
    with jsx.open('x',encoding='utf-8') as f:
        f.write(template.replace('__CONFIG__',json.dumps(cfg,ensure_ascii=True)))
    exe=Path(resolve_photoshop_exe())
    subprocess.Popen([str(exe),'-r',str(jsx)])
    print('Prueba enviada a Photoshop 2025. Salidas: '+str(out))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        from typeo_core import TypeoError
        if isinstance(exc, TypeoError):
            print('[TYPEO] REQUIERE REVISION: '+str(exc), file=sys.stderr)
            raise SystemExit(2) from exc
        raise
