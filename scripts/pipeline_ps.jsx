(function(){
var job=__PIPELINE__;
var s=stringIDToTypeID,oldUnits=app.preferences.rulerUnits,oldDialogs=app.displayDialogs,oldMaxCompat;
try{oldMaxCompat=app.preferences.maximizeCompatibility;app.preferences.maximizeCompatibility=QueryModes.ALWAYS;}catch(ignoreCompat){}
function jq(v){return '"'+String(v).replace(/\\/g,'\\\\').replace(/"/g,'\\"').replace(/\r/g,'\\r').replace(/\n/g,'\\n').replace(/\t/g,'\\t')+'"';}
function encode(v){
    if(v===null)return 'null';if(typeof v==='string')return jq(v);if(typeof v==='number'||typeof v==='boolean')return String(v);
    var out=[];if(v instanceof Array){for(var i=0;i<v.length;i++)out.push(encode(v[i]));return '['+out.join(',')+']';}
    for(var key in v)if(v.hasOwnProperty(key))out.push(jq(key)+':'+encode(v[key]));return '{'+out.join(',')+'}';
}
function write(path,obj){var f=new File(path);f.encoding='UTF8';if(!f.open('w'))throw new Error('No se puede escribir '+path);f.write(encode(obj));f.close();}
function read(path){
    var f=new File(path);if(!f.exists)return null;f.encoding='UTF8';if(!f.open('r'))return null;var text=f.read();f.close();
    try{if(typeof JSON!=='undefined'&&JSON.parse)return JSON.parse(text);
        // Validacion JSON2 antes de eval: solo datos, nunca expresiones o codigo del guion.
        if(!/^[\],:{}\s]*$/.test(text.replace(/\\(?:["\\\/bfnrt]|u[0-9a-fA-F]{4})/g,'@').replace(/"[^"\\\n\r]*"|true|false|null|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?/g,']').replace(/(?:^|:|,)(?:\s*\[)+/g,'')))throw new Error('JSON invalido');
        return eval('('+text+')');
    }catch(e){throw new Error('No se puede leer JSON '+path+': '+e.message);}
}
function event(stage,page,extra){var f=new File(job.native_events);f.encoding='UTF8';f.open('a');f.writeln(encode({time_ms:new Date().getTime(),stage:stage,page:page||null,extra:extra||null}));f.close();}
function choose(states,next,translations,masks){
    if(next>=states.length)return {action:'complete',index:-1};
    if(states[next].clean&&translations[next])return {action:'typeo',index:next};
    for(var p=next;p<states.length;p++)if(!states[p].clean&&masks[p])return {action:'clean_step',index:p};
    return {action:'wait',index:-1};
}
function mergeMaskContext(ready,clean){
    if(clean.regiones_protegidas!==undefined)ready.regiones_protegidas=clean.regiones_protegidas;
    if(clean.repaso_fondos_ocr!==undefined)ready.repaso_fondos=clean.repaso_fondos_ocr.concat(ready.repaso_fondos_geometria||[]);
    return ready;
}
function openRawFresh(pageConfig){
    // Photoshop reutiliza app.open(path) si esa RAW ya tiene una pestaña
    // modificada. La entrada temporal fuerza una lectura nueva del disco.
    var rawFile=new File(pageConfig.raw);
    var extension=rawFile.name.substring(rawFile.name.lastIndexOf('.'));
    var input=new File(pageConfig.folder+'/__raw_'+job.job_id+extension);
    if(!rawFile.copy(input.fsName))throw new Error('No se puede cargar RAW nueva: '+pageConfig.page);
    var doc;
    try{doc=app.open(input);}finally{if(input.exists&&!input.remove())throw new Error('No se pudo retirar la entrada temporal RAW');}
    if(doc.layers.length!==1||doc.layers[0].typename!=='ArtLayer'||doc.layers[0].kind===LayerKind.TEXT)throw new Error('La apertura RAW no es una imagen limpia');
    return doc;
}
function check(){
    var error=read(job.worker_error);if(error)throw new Error('Traduccion/mascaras: '+error.message);
    if(new File(job.cancel).exists)throw new Error('Cancelacion solicitada; no guardar trabajo parcial como final');
}
function ensureActiveDoc(doc){if(app.activeDocument!==doc)app.activeDocument=doc;}
function ensureComponentChannels(doc){if(!doc.componentChannels)return;try{if(doc.activeChannels&&doc.activeChannels.length===doc.componentChannels.length)return;}catch(e){}doc.activeChannels=doc.componentChannels;}
function selectLayerTransparency(doc,layer){
    ensureActiveDoc(doc);doc.activeLayer=layer;
    var c=charIDToTypeID,d=new ActionDescriptor(),r1=new ActionReference(),r2=new ActionReference();
    r1.putProperty(c('Chnl'),c('fsel'));d.putReference(c('null'),r1);
    r2.putEnumerated(c('Chnl'),c('Chnl'),c('Trsp'));d.putReference(c('T   '),r2);
    executeAction(c('setd'),d,DialogModes.NO);
    var b=doc.selection.bounds;if(!b)throw new Error('Capa sin pixeles visibles: '+layer.name);
}
function loadMaskAlpha(doc,path,channelName){
    var f=new File(path);if(!f.exists)throw new Error('Falta mascara '+path);
    var mask=app.open(f),alpha=null;
    try{
        if(mask.mode!==DocumentMode.RGB)mask.changeMode(ChangeMode.RGB);
        try{
            alpha=mask.channels[0].duplicate(doc);
            alpha.name=channelName||'Temp_Alpha_Limpieza';
        }catch(dupErr){
            alpha=null;app.activeDocument=mask;mask.selection.selectAll();mask.selection.copy();
        }
    }finally{mask.close(SaveOptions.DONOTSAVECHANGES);}
    ensureActiveDoc(doc);
    if(alpha===null){
        for(var safe=0;safe<doc.layers.length;safe++)if(doc.layers[safe].name==='LIMPIEZA_BASE'&&doc.layers[safe].typename==='ArtLayer'){
            doc.activeLayer=doc.layers[safe];break;
        }
        alpha=doc.channels.add();alpha.name=channelName||'Temp_Alpha_Limpieza';
        try{doc.activeChannels=[alpha];doc.paste();}
        catch(pasteErr){ensureComponentChannels(doc);alpha.remove();throw pasteErr;}
    }
    ensureComponentChannels(doc);
    return alpha;
}
function selectMask(doc,path){
    var alpha=loadMaskAlpha(doc,path,'Temp_Alpha_Limpieza');
    try{ensureComponentChannels(doc);doc.selection.load(alpha,SelectionType.REPLACE,false);}
    finally{ensureComponentChannels(doc);alpha.remove();}
    // Una mascara marcada como no vacia nunca se ignora silenciosamente.
    var b=doc.selection.bounds;if(!b)throw new Error('Seleccion vacia para '+path);
}
function generative(doc,base,index,selectionPrepared){
    if(selectionPrepared!==true){doc.selection.expand(2);doc.selection.feather(1);}
    doc.activeLayer=base;
    var previous=doc.activeLayer.id,count=doc.layers.length,actionError='';
    try{app.doAction('GenFillAuto','MangaAuto');}
    catch(e){
        actionError=e.message;doc.activeLayer=base;
        var desc=new ActionDescriptor();desc.putString(s('prompt'),'');
        try{executeAction(s('syntheticFill'),desc,DialogModes.NO);}
        catch(f){throw new Error('Relleno generativo fallo. Accion: '+actionError+'; native: '+f.message);}
    }
    if(doc.activeLayer.id===previous||doc.layers.length<=count)throw new Error('GenFill no produjo una capa independiente');
    doc.activeLayer.name='IA_Generativa_Par_'+index;doc.selection.deselect();
    return doc.activeLayer.id;
}
function boundGenerativeLayer(doc,layer,path,index,replaceMask,useLayerAlpha,savedAlpha){
    var existing=layer.typename==='LayerSet'&&layer.layers.length===1&&layer.layers[0].name==='ContenidoGenerativo_'+index;
    if(existing){
        var maskRef=new ActionReference();maskRef.putIdentifier(s('layer'),layer.id);
        var info=executeActionGet(maskRef);
        if(info.hasKey(s('hasUserMask'))&&info.getBoolean(s('hasUserMask'))){
            if(!replaceMask)return layer;
            doc.activeLayer=layer;
            var del=new ActionDescriptor(),mr=new ActionReference();mr.putEnumerated(s('channel'),s('channel'),s('mask'));
            del.putReference(s('null'),mr);executeAction(s('delete'),del,DialogModes.NO);
        }
    }
    // Algunas acciones devuelven una generacion opaca fuera de la seleccion.
    // Acotarla con mascara externa evita tapar pincel u otros rellenos, sin
    // rasterizar ni perder las alternativas de la capa generativa original.
    ensureActiveDoc(doc);
    if(savedAlpha){doc.selection.load(savedAlpha,SelectionType.REPLACE,false);}
    else if(useLayerAlpha===true){selectLayerTransparency(doc,layer);doc.selection.expand(2);doc.selection.feather(1);}
    else{selectMask(doc,path);doc.selection.expand(2);doc.selection.feather(1);}
    var group=existing?layer:doc.layerSets.add();group.name='IA_Generativa_Par_'+index;
    if(!existing){layer.name='ContenidoGenerativo_'+index;layer.move(group,ElementPlacement.INSIDE);}
    doc.activeLayer=group;
    var c=charIDToTypeID,d=new ActionDescriptor(),ref=new ActionReference();
    d.putClass(c('Nw  '),c('Chnl'));ref.putEnumerated(c('Chnl'),c('Chnl'),c('Msk '));
    d.putReference(c('At  '),ref);d.putEnumerated(c('Usng'),c('UsrM'),c('RvlS'));
    executeAction(c('Mk  '),d,DialogModes.NO);
    ensureComponentChannels(doc);doc.selection.deselect();return group;
}
function layerWithId(layers,id){
    for(var i=0;i<layers.length;i++){
        if(layers[i].id===id)return layers[i];
        if(layers[i].typename==='LayerSet'){var found=layerWithId(layers[i].layers,id);if(found)return found;}
    }return null;
}
function finishCleanPixels(doc,patches,maskPath,protectedArt){
    ensureActiveDoc(doc);ensureComponentChannels(doc);
    for(var old=doc.layers.length-1;old>=0;old--)if(/^LIMPIEZA_REPASO_/.test(doc.layers[old].name))doc.layers[old].remove();
    if(!patches||!patches.length)return;
    var needMask=false;
    for(var chk=0;chk<patches.length;chk++)if(patches[chk].area_revisada!==true&&patches[chk].poligonos&&patches[chk].poligonos.length){needMask=true;break;}
    var maskAlpha=(needMask&&maskPath)?loadMaskAlpha(doc,maskPath,'Temp_Alpha_Repaso'):null;
    try{
        for(var n=0;n<patches.length;n++){
            var patch=patches[n];
            doc.activeLayer=doc.layers[0];
            var repair=doc.artLayers.add();repair.name='LIMPIEZA_REPASO_'+(n+1);
            if(patch.debajo_generativas){
                for(var k=0;k<doc.layers.length;k++)if(doc.layers[k].name==='LIMPIEZA_PINCEL'){repair.move(doc.layers[k],ElementPlacement.PLACEBEFORE);break;}
            }else if(repair.id!==doc.layers[0].id)repair.move(doc.layers[0],ElementPlacement.PLACEBEFORE);
            doc.activeLayer=repair;
            var color=new SolidColor();color.rgb.red=patch.rgb[0];color.rgb.green=patch.rgb[1];color.rgb.blue=patch.rgb[2];
            for(var q=0;q<patch.poligonos.length;q++){
                if(patch.area_revisada===true){doc.selection.select(patch.poligonos[q]);}
                else{
                    if(!maskAlpha)throw new Error('Falta mascara '+maskPath);
                    ensureComponentChannels(doc);doc.selection.load(maskAlpha,SelectionType.REPLACE,false);
                    doc.selection.select(patch.poligonos[q],SelectionType.INTERSECT);
                }
                try{var selected=doc.selection.bounds;if(!selected)continue;}catch(empty){continue;}
                doc.selection.expand(2);doc.selection.feather(.5);
                for(var p=0;p<protectedArt.length;p++)doc.selection.select(protectedArt[p],SelectionType.DIMINISH);
                try{var remains=doc.selection.bounds;if(!remains)continue;}catch(protectedOnly){continue;}
                doc.activeLayer=repair;
                doc.selection.fill(color,ColorBlendMode.NORMAL,100,false);doc.selection.deselect();
            }
        }
    }finally{if(maskAlpha){ensureComponentChannels(doc);maskAlpha.remove();}}
}
function hasLayer(layers,id){
    for(var a=0;a<layers.length;a++){
        if(layers[a].id===id)return true;
        if(layers[a].typename==='LayerSet'&&hasLayer(layers[a].layers,id))return true;
    }return false;
}
function cleanStep(state,page){
    var doc=state.doc;ensureActiveDoc(doc);ensureComponentChannels(doc);
    if(!state.initialized){
        state.mask=read(page.clean_ready);if(!state.mask)return false;
        if(state.mask.job_id!==job.job_id)throw new Error('Mascaras de otra ejecucion');
        event('clean_start',page.page);
        doc.activeLayer.name='ORIGINAL_TRADUCCION';state.original=doc.activeLayer;
        state.base=doc.activeLayer.duplicate();state.base.name='LIMPIEZA_BASE';
        state.brush=doc.artLayers.add();state.brush.name='LIMPIEZA_PINCEL';state.generativeIds=[];
        state.initialized=true;state.step=-1;
    }
    if(state.step===-1){
        if(state.mask.pincel){
            selectMask(doc,state.mask.pincel);doc.activeLayer=state.brush;
            var white=new SolidColor();white.rgb.red=255;white.rgb.green=255;white.rgb.blue=255;
            doc.selection.fill(white,ColorBlendMode.NORMAL,100,false);doc.selection.deselect();
        }
        state.step=0;event('clean_brush',page.page);return true;
    }
    if(state.step<state.mask.pares.length){
        var localPath=state.mask.capas_locales&&state.mask.capas_locales[state.step];
        event('clean_genfill_start',page.page,{pair:state.step+1,motor:localPath?'comic_local':'genfill'});
        var generated,limited;
        if(localPath){
            var localDoc=app.open(new File(localPath));
            try{
                var localLayer=localDoc.activeLayer.duplicate(doc,ElementPlacement.PLACEATBEGINNING);
                generated=localLayer.id;
            }finally{localDoc.close(SaveOptions.DONOTSAVECHANGES);ensureActiveDoc(doc);}
            limited=boundGenerativeLayer(doc,layerWithId(doc.layers,generated),state.mask.pares[state.step],state.step+1,false,true,null);
        }else{
            selectMask(doc,state.mask.pares[state.step]);
            doc.selection.expand(2);doc.selection.feather(1);
            var savedAlpha=doc.channels.add();savedAlpha.name='Temp_Alpha_GenFill';
            try{
                doc.selection.store(savedAlpha);
                generated=generative(doc,state.base,state.step+1,true);
                limited=boundGenerativeLayer(doc,layerWithId(doc.layers,generated),state.mask.pares[state.step],state.step+1,false,false,savedAlpha);
            }finally{ensureComponentChannels(doc);savedAlpha.remove();}
        }
        state.generativeIds.push(limited.id);state.step++;
        event('clean_genfill_complete',page.page,{pair:state.step,motor:localPath?'comic_local':'genfill'});return true;
    }
    // El original y todas las capas generativas siguen siendo editables e independientes.
    if(state.original.name!=='ORIGINAL_TRADUCCION'||state.base.name!=='LIMPIEZA_BASE')throw new Error('Estructura de limpieza alterada');
    state.clean=true;doc.selection.deselect();
    write(page.clean_report,{status:'complete',job_id:job.job_id,page:page.page,generative_layer_ids:state.generativeIds,psd_intermedio:false});
    event('clean_complete',page.page);return true;
}
try{
    app.preferences.rulerUnits=Units.PIXELS;app.displayDialogs=DialogModes.NO;app.bringToFront();
    var opened=false;
    for(var offset=0;offset<job.pages.length;offset+=50){
        var end=Math.min(offset+50,job.pages.length),states=[];
        for(var i=offset;i<end;i++){
            var pageConfig=job.pages[i];
            var doc;
            var prepared=job.prepared_inputs&&job.prepared_inputs[pageConfig.page];
            if(prepared){
                doc=null;
                for(var found=0;found<app.documents.length;found++)if(app.documents[found].name===prepared.name){
                    var candidate=app.documents[found],matches=false,used=false;
                    for(var prior=0;prior<states.length;prior++)if(states[prior].doc.id===candidate.id)used=true;
                    if(used)continue;
                    try{matches=candidate.fullName.fsName.toLowerCase()===new File(prepared.path).fsName.toLowerCase();}
                    catch(noPath){matches=true;} // Entrada temporal retirada; el UUID del nombre sigue siendo unico.
                    if(matches){doc=candidate;break;}
                }
                if(!doc)throw new Error('El documento preparado ya no esta abierto: '+pageConfig.page);
                app.activeDocument=doc;
            }
            else if(job.reuse_final){
                doc=app.open(new File(pageConfig.output));
                if(!doc.saved&&job.allow_open_replacement){
                    doc.close(SaveOptions.DONOTSAVECHANGES);doc=app.open(new File(pageConfig.output));
                }
            }
            else{
                doc=openRawFresh(pageConfig);
            }
            if(doc.mode!==DocumentMode.RGB)doc.changeMode(ChangeMode.RGB);
            var state={doc:doc,initialized:false,clean:false,complete:false};
            if(job.reuse_final||prepared){
                if(doc.width.as('px')!==pageConfig.geometry.width||doc.height.as('px')!==pageConfig.geometry.height)throw new Error('El PSD anterior tiene otras dimensiones');
                state.generativeIds=[];
                for(var l=0;l<doc.layers.length;l++){
                    var layer=doc.layers[l];
                    if(layer.name==='ORIGINAL_TRADUCCION')state.original=layer;
                    if(layer.name==='LIMPIEZA_BASE')state.base=layer;
                    if(layer.name==='LIMPIEZA_PINCEL')state.brush=layer;
                    if(/^IA_Generativa_Par_/.test(layer.name))state.generativeIds.push(layer.id);
                }
                if(!state.original||!state.base||!state.brush)throw new Error('El PSD anterior no conserva la limpieza editable');
                state.clean=true;state.initialized=true;
            }
            states.push(state);event('page_opened',pageConfig.page);
        }
        if(!opened){write(job.opened,{status:'opened',job_id:job.job_id});opened=true;event('pages_opened');}
        if(job.reuse_final||job.prepared_inputs)for(var reused=offset;reused<end;reused++){event('clean_start',job.pages[reused].page,{reused:true});event('clean_complete',job.pages[reused].page,{reused:true});}
        var next=0,knownMasks=[],knownTranslations=[];
        while(next<states.length){
            check();var current=states[next],page=job.pages[offset+next];
            if(job.clean_only&&current.clean){
                ensureActiveDoc(current.doc);
                if(new File(page.output).exists&&!job.replace)throw new Error('El PSD final ya existe');
                if(!hasLayer(current.doc.layers,current.original.id)||!hasLayer(current.doc.layers,current.base.id)||!hasLayer(current.doc.layers,current.brush.id))throw new Error('Falta capa de limpieza');
                for(var g=0;g<current.generativeIds.length;g++)if(!hasLayer(current.doc.layers,current.generativeIds[g]))throw new Error('Falta capa generativa');
                var psd=new PhotoshopSaveOptions();psd.layers=true;
                activateFinalDocument(current.doc,page.output);
                current.doc.saveAs(new File(page.output),psd,false,Extension.LOWERCASE);
                write(page.clean_report,{status:'complete',job_id:job.job_id,page:page.page,generative_layer_ids:current.generativeIds,final_verified:true,psd_intermedio:false});
                write(page.result,{status:'complete',job_id:job.job_id,page:page.page,phase:'limpieza'});
                event('page_complete',page.page,{output:page.output});next++;continue;
            }
            // El typeo ordenado tiene prioridad entre acciones de Photoshop.
            var translations=[],masks=[];
            for(var r=next;r<states.length;r++){
                if(!knownMasks[r])knownMasks[r]=new File(job.pages[offset+r].clean_ready).exists;
                if(!knownTranslations[r])knownTranslations[r]=knownMasks[r]&&new File(job.pages[offset+r].typeo_ready).exists;
                translations[r]=knownTranslations[r];
                masks[r]=knownMasks[r];
            }
            var decision=choose(states,next,translations,masks);
            if(decision.action==='typeo'){
                var ready=read(page.typeo_ready);
                if(ready.job_id!==job.job_id)throw new Error('Traduccion de otra ejecucion');
                ensureActiveDoc(current.doc);
                event('typeo_start',page.page);
                if(!job.external_clean&&!job.reuse_final&&job.reuse_masks&&job.reuse_masks[page.page]){
                    var masksForReuse=read(page.clean_ready).limites_generativos||job.reuse_masks[page.page];
                    if(masksForReuse.length!==current.generativeIds.length)throw new Error('Las mascaras originales no corresponden a las capas generativas');
                    for(var bounded=0;bounded<current.generativeIds.length;bounded++){
                        var originalGen=layerWithId(current.doc.layers,current.generativeIds[bounded]);
                        var match=/IA_Generativa_Par_(\d+)/.exec(originalGen.name);
                        var number=match?parseInt(match[1],10):bounded+1;
                        current.generativeIds[bounded]=boundGenerativeLayer(current.doc,originalGen,masksForReuse[number-1],number,true).id;
                    }
                }
                if(job.reuse_final||job.prepared_inputs){
                    var previous=job.old_typeo_ids[page.page]||[];
                    for(var n=current.doc.layers.length-1;n>=0;n--){
                        var oldLayer=current.doc.layers[n];if(oldLayer.typename!=='ArtLayer'||oldLayer.kind!==LayerKind.TEXT)continue;
                        var oldId=oldLayer.name.split(' | ')[0],managed=false;
                        for(var m=0;m<previous.length;m++)if(previous[m]===oldId){managed=true;break;}
                        if(managed)oldLayer.remove();
                    }
                }
                var cleanPaths=read(page.clean_ready);
                mergeMaskContext(ready,cleanPaths);
                if(job.reuse_final&&ready.reaplicar_pincel===true&&cleanPaths.pincel){
                    selectMask(current.doc,cleanPaths.pincel);current.doc.activeLayer=current.brush;
                    var inkWhite=new SolidColor();inkWhite.rgb.red=255;inkWhite.rgb.green=255;inkWhite.rgb.blue=255;
                    current.doc.selection.fill(inkWhite,ColorBlendMode.NORMAL,100,false);current.doc.selection.deselect();
                }
                finishCleanPixels(current.doc,ready.repaso_fondos||[],cleanPaths.generativo,cleanPaths.arte_protegido||[]);
                var verifyClean=function(d){
                    if(!hasLayer(d.layers,current.original.id)||!hasLayer(d.layers,current.base.id)||!hasLayer(d.layers,current.brush.id))throw new Error('Falta una capa de limpieza antes de guardar');
                    if(current.original.kind===LayerKind.TEXT||current.base.kind===LayerKind.TEXT)throw new Error('El original RAW fue sustituido por texto');
                    if(!job.reuse_final){
                        var texts=0;for(var t=0;t<d.layers.length;t++)if(d.layers[t].typename==='ArtLayer'&&d.layers[t].kind===LayerKind.TEXT)texts++;
                        if(texts!==ready.items.length)throw new Error('Hay textos anteriores superpuestos en el documento');
                    }
                    for(var q=0;q<current.generativeIds.length;q++)if(!hasLayer(d.layers,current.generativeIds[q]))throw new Error('Falta una capa generativa antes de guardar');
                };
                ready.on_stage=function(stage){event(stage,page.page);};
                if(!renderTypeo(ready,current.doc,verifyClean)){
                    var failed=read(page.result);
                    throw new Error('Fallo de typeo/revision en '+page.page+': '+(failed?failed.message:'sin informe'));
                }
                if(!hasLayer(current.doc.layers,current.original.id)||!hasLayer(current.doc.layers,current.base.id)||!hasLayer(current.doc.layers,current.brush.id))throw new Error('Falta una capa de limpieza en el PSD final');
                for(var lid=0;lid<current.generativeIds.length;lid++)if(!hasLayer(current.doc.layers,current.generativeIds[lid]))throw new Error('Se perdio una capa generativa del PSD final');
                write(page.clean_report,{status:'complete',job_id:job.job_id,page:page.page,generative_layer_ids:current.generativeIds,final_verified:true,psd_intermedio:false});
                current.complete=true;event('page_complete',page.page,{output:page.output});next++;continue;
            }
            // Si la traduccion de la primera pendiente tarda, avanzar la limpieza siguiente.
            if(decision.action==='clean_step'){
                cleanStep(states[decision.index],job.pages[offset+decision.index]);
            }else{
                $.sleep(50);
            }
        }
    }
    write(job.native_status,{status:'complete',job_id:job.job_id});event('pipeline_complete');
}catch(e){write(job.native_status,{status:'error',job_id:job.job_id,message:e.message+' | linea '+e.line});event('pipeline_error',null,e.message);}
finally{app.preferences.rulerUnits=oldUnits;app.displayDialogs=oldDialogs;if(oldMaxCompat!==undefined){try{app.preferences.maximizeCompatibility=oldMaxCompat;}catch(ignoreCompatRestore){}}}
})();
