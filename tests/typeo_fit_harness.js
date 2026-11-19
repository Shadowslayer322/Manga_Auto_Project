const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('scripts/typeo_ps.jsx','utf8');
const c={};vm.createContext(c);vm.runInContext(source.slice(0,source.indexOf('function activateFinalDocument')),c);
for(const ratio of [20/18,20/22]){
 let size=72,count=0;
 while(size*4+10>130){
  const next=c.typeoFitSize(size,12,size*4+10,size+10,130,100);
  assert(next!==null&&next<size&&next>=12);
  size=next;assert(++count<6);
  assert(Math.abs(c.typeoLeadingPx({interlineado_ratio:ratio},size)/size-ratio)<1e-9);
 }
}
assert.strictEqual(c.typeoFitSize(18,18,200,100,100,100),null);
assert.strictEqual(c.typeoFitSize(18,12,80,40,100,100),18);
console.log('Ajuste proporcional: menos de 6 mediciones, proporcion y minimo conservados.');
