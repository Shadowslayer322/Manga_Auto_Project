// Ejecutar las funciones reales del renderer, incluida la regresion de la variable q.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const source = fs.readFileSync(path.join(__dirname, '../scripts/typeo_ps.jsx'), 'utf8');
const prefix = source.slice(source.indexOf('function jsonQuote'), source.indexOf('function say'));
const sandbox = { cfg: { result: 'none', job_id: 'test', page: '001.jpg' }, saved: '' };
sandbox.File = function () { this.open=()=>true; this.write=t=>sandbox.saved=t; this.close=()=>{}; };
vm.createContext(sandbox);
vm.runInContext(prefix + `var q={before:[1,2]}; result('complete', 'comillas " y salto\\n y ruta C:\\\\test');`, sandbox);
const result = JSON.parse(sandbox.saved);
if (result.status !== 'complete' || result.job_id !== 'test' || !result.message.includes('"')) throw Error('Estado invalido');
console.log('Estado JSX serializado y parseado correctamente');
