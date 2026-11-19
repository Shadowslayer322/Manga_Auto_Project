"""Descarga explicita del modelo oficial; nunca descargar durante una limpieza."""
from pathlib import Path
import hashlib
import urllib.request
from typeo_core import BASE,read_json,TypeoError


def main():
    config=read_json(BASE/'config/ocr_ingles.json');path=BASE/config['modelo']
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==config['sha256']:
        print('Modelo ingles verificado: '+str(path));return
    url='https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv5/rec/en_PP-OCRv5_rec_mobile.onnx'
    with urllib.request.urlopen(url,timeout=90) as response:data=response.read()
    if hashlib.sha256(data).hexdigest()!=config['sha256']:raise TypeoError('Huella del modelo diferente a la publicada')
    path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix('.download');temp.write_bytes(data);temp.replace(path)
    print('Modelo ingles instalado y verificado: '+str(path))


if __name__=='__main__':main()
