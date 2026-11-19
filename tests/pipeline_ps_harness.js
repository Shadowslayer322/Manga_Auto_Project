// Prueba las funciones reales de planificacion y lectura del controlador de Photoshop.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const source = fs.readFileSync(path.join(__dirname, '../scripts/pipeline_ps.jsx'), 'utf8').replace(/\r\n/g,'\n');
const functions = source.slice(source.indexOf('function jq'), source.lastIndexOf('try{\n    app.preferences'));
const sandbox = { job: {}, JSON: undefined, content: '', malicious: false };
sandbox.File = function () {
  this.exists = true; this.open = () => true; this.read = () => sandbox.content;
  this.close = () => {}; this.write = () => {}; this.writeln = () => {};
};
vm.createContext(sandbox);
vm.runInContext(functions, sandbox);
const evaluate = code => vm.runInContext(code, sandbox);
const decision = (states, next, translations, masks) => evaluate(`choose(${JSON.stringify(states)},${next},${JSON.stringify(translations)},${JSON.stringify(masks)}).action`);
if (decision([{clean:true},{clean:false}],0,[true,false],[true,true]) !== 'typeo') throw Error('No dio prioridad al typeo listo');
if (decision([{clean:true},{clean:false}],0,[false,true],[true,true]) !== 'clean_step') throw Error('No avanzo limpieza durante espera');
if (decision([{clean:false},{clean:true}],0,[false,true],[false,true]) !== 'wait') throw Error('Typeo fuera de orden');
if (decision([],0,[],[]) !== 'complete') throw Error('Finalizacion incorrecta');
sandbox.content = JSON.stringify({job_id:'test',text:'¿Hola? “Mimi”',panels:[[1,2],[3,4]], ready:true});
if (evaluate('read("test").text') !== '¿Hola? “Mimi”') throw Error('JSON valido rechazado');
sandbox.content='{"x":(function(){malicious=true;return 1;})()}';
let rejected=false;try{evaluate('read("test")');}catch(e){rejected=true;}
if (!rejected || sandbox.malicious) throw Error('Se ejecuto contenido no JSON');
console.log('Planificador ordenado, prioridad inmediata y lector JSON seguro: OK');

const merged=evaluate('mergeMaskContext({regiones_protegidas:["stale"],repaso_fondos:["old"],repaso_fondos_geometria:["manual"]},{regiones_protegidas:["hours","sfx"],repaso_fondos_ocr:["ocr"]})');
if(JSON.stringify(merged.regiones_protegidas)!=='["hours","sfx"]')throw Error('Protecciones perdidas por carrera con OCR');
if(JSON.stringify(merged.repaso_fondos)!=='["ocr","manual"]')throw Error('Repasos perdidos o duplicados');
console.log('Contexto OCR listo antes del renderizado: OK');

const paintCalls = [];
sandbox.app = {};
sandbox.SolidColor = function () { this.rgb = {}; };
sandbox.ColorBlendMode = {NORMAL: 'normal'};
sandbox.SelectionType = {DIMINISH: 'subtract'};
const repair = {id: 1};
sandbox.paintDoc = {
  layers: [repair],
  artLayers: {add: () => repair},
  selection: {
    bounds: [1, 1, 10, 10],
    select: (_, operation) => paintCalls.push(operation || 'select'),
    expand: () => paintCalls.push('expand'),
    feather: () => paintCalls.push('feather'),
    fill: () => paintCalls.push('fill'),
    deselect: () => {}
  }
};
evaluate('finishCleanPixels(paintDoc,[{area_revisada:true,rgb:[255,255,255],poligonos:[[[1,1],[10,1],[10,10]]]}],null,[[[5,5],[8,5],[8,8]]])');
if (paintCalls.join(',') !== 'select,expand,feather,subtract,fill') throw Error('El repaso invadio el arte protegido');
console.log('Los repasos respetan el arte protegido después de expandir la selección: OK');
