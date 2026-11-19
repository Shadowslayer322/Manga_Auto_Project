"""Crear una plantilla pendiente para revisar nuevas paginas, sin inventar paneles."""
import argparse
from pathlib import Path
from PIL import Image
from typeo_core import BASE, TypeoError, read_json, sha256, write_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifiesto',type=Path,help='Manifiesto antiguo opcional; por defecto usa las zonas OCR actuales')
    parser.add_argument('--salida',type=Path,default=BASE/'config/typeo_geometria_pendiente.json')
    args=parser.parse_args()
    if args.salida.exists():
        raise TypeoError('La plantilla ya existe; elegir otra salida para no perder revisiones')
    pages=[]
    if args.manifiesto is None:
        from ocr_ingles import geometry_from_record
        for raw in sorted((BASE/'01_RAW').iterdir()):
            if raw.suffix.lower() not in {'.jpg','.jpeg','.png','.webp'}:continue
            path=BASE/'04_DIAGNOSTICO/mascaras_produccion'/raw.stem/'mascaras.json'
            if not path.exists():raise TypeoError('Falta deteccion/OCR actual de '+raw.name)
            record=read_json(path)
            if record['raw_sha256']!=sha256(raw):raise TypeoError('Coordenadas de otra RAW: '+raw.name)
            pages.append(geometry_from_record(raw,record))
        write_json(args.salida,{'version':1,'estado':'pendiente_revision','paginas':pages})
        print('Plantilla OCR creada para revision: '+str(args.salida));return
    for page in read_json(args.manifiesto):
        raw=BASE/'01_RAW'/page['archivo']
        with Image.open(raw) as im:width,height=im.size
        zones=[]
        for z in page['zonas']:
            poly=z.get('poligono_contenedor') or z.get('poligono_globo')
            zones.append({'id':Path(page['archivo']).stem+f'_{z["id"]:02d}',
                'texto_original':'','box_contenedor':z['box_contenedor'],
                'poligono_globo':poly,'poligono_panel':[],
                'tipo_contenedor':'globo' if poly else 'pendiente_revision',
                'metodo_limpieza':z['tipo'],'permite_fuera_panel_raw':False,
                'rol_revisado':'normal','trazo_px':5 if z['tipo']=='relleno_generativo' else 0,
                'trazo_rgb':[255,255,255],'relleno_rgb':[0,0,0],
                'margen_revision_px':6,'tamano_px':34,
                'pendiente':'Revisar RAW: original, panel, globo incluso transparente, estilo/color y exclusion de SFX'})
        pages.append({'archivo':page['archivo'],'width':width,'height':height,
                      'raw_sha256':sha256(raw),'zonas':zones})
    write_json(args.salida,{'version':1,'estado':'pendiente_revision','paginas':pages})
    print('Plantilla creada. Completar y revisar antes de usarla: '+str(args.salida))


if __name__=='__main__':main()
