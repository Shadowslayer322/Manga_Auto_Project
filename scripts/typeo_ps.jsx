// Tamano e interlineado se escalan juntos, sin rasterizar el texto.
function typeoLeadingPx(it,size){
    var ratio=it.interlineado_ratio||(it.interlineado_px&&it.tamano_px?it.interlineado_px/it.tamano_px:1.16);
    return size*ratio;
}
function typeoFitSize(size,minSize,width,height,maxWidth,maxHeight){
    if(width<=maxWidth&&height<=maxHeight)return size;
    if(size<=minSize)return null;
    var factor=Math.min(maxWidth/Math.max(width,1),maxHeight/Math.max(height,1));
    // Medir de nuevo tras escalar: bordes y metricas pueden variar un poco.
    return Math.max(minSize,Math.min(size-0.5,size*factor*0.99));
}
function activateFinalDocument(doc,path,allowUnsavedReplacement){
    var target=new File(path).fsName.toLowerCase();
    for(var i=app.documents.length-1;i>=0;i--){
        var other=app.documents[i];if(other.id===doc.id)continue;
        var same=false;try{same=other.fullName.fsName.toLowerCase()===target;}catch(noFile){}
        if(!same)continue;
        // Solo relevar la pestaña guardada de este mismo resultado. Nunca
        // cerrar ni duplicar una pestaña con ediciones pendientes del usuario.
        if(!other.saved){
            if(!allowUnsavedReplacement)throw new Error('El PSD final tiene cambios sin guardar; conservarlos antes de actualizar: '+other.name);
            other.close(SaveOptions.DONOTSAVECHANGES);
        }else{other.close(SaveOptions.SAVECHANGES);}
    }
    app.activeDocument=doc;
}

function intersectsProtected(b,poly){
    var rect=[[b[0],b[1]],[b[2],b[1]],[b[2],b[3]],[b[0],b[3]]],axes=[[1,0],[0,1]];
    for(var i=0;i<poly.length;i++){var p=poly[i],q=poly[(i+1)%poly.length];axes.push([p[1]-q[1],q[0]-p[0]]);}
    for(var a=0;a<axes.length;a++){
        var axis=axes[a],rmin=Infinity,rmax=-Infinity,pmin=Infinity,pmax=-Infinity;
        if(axis[0]===0&&axis[1]===0)continue;
        for(var r=0;r<rect.length;r++){var v=rect[r][0]*axis[0]+rect[r][1]*axis[1];rmin=Math.min(rmin,v);rmax=Math.max(rmax,v);}
        for(var n=0;n<poly.length;n++){var x=poly[n][0]*axis[0]+poly[n][1]*axis[1];pmin=Math.min(pmin,x);pmax=Math.max(pmax,x);}
        if(rmax<=pmin||pmax<=rmin)return false;
    }return true;
}

function renderTypeo(cfg, suppliedDoc, beforeSave){
var log=new File(cfg.log);log.encoding='UTF8';log.open('w');
var units=app.preferences.rulerUnits, dialogs=app.displayDialogs, smartQuotes, maxCompat;
try{smartQuotes=app.preferences.useSmartQuotes;app.preferences.useSmartQuotes=false;}catch(ignoreQuotes){}
try{maxCompat=app.preferences.maximizeCompatibility;app.preferences.maximizeCompatibility=QueryModes.ALWAYS;}catch(ignoreCompat){}
var s=stringIDToTypeID;
function jsonQuote(t){return '"'+String(t).replace(/\\/g,'\\\\').replace(/"/g,'\\"').replace(/\r/g,'\\r').replace(/\n/g,'\\n').replace(/\t/g,'\\t')+'"';}
function result(status,message){var f=new File(cfg.result);f.encoding='UTF8';f.open('w');f.write('{"status":'+jsonQuote(status)+',"job_id":'+jsonQuote(cfg.job_id)+',"page":'+jsonQuote(cfg.page)+',"message":'+jsonQuote(message)+'}');f.close();}
function say(t){log.writeln(t);}
function bounds(layer){var b=layer.bounds;return [b[0].as('px'),b[1].as('px'),b[2].as('px'),b[3].as('px')];}
function stroke(layer,it){
    if(!it.trazo_px)return;
    var desc=new ActionDescriptor(),ref=new ActionReference();
    ref.putProperty(s('property'),s('layerEffects'));ref.putEnumerated(s('layer'),s('ordinal'),s('targetEnum'));desc.putReference(s('null'),ref);
    var fx=new ActionDescriptor(),fr=new ActionDescriptor(),color=new ActionDescriptor();
    fx.putUnitDouble(s('scale'),s('percentUnit'),100);
    fr.putBoolean(s('enabled'),true);fr.putBoolean(s('present'),true);fr.putBoolean(s('showInDialog'),true);
    fr.putEnumerated(s('style'),s('frameStyle'),s('outsetFrame'));fr.putEnumerated(s('paintType'),s('frameFill'),s('solidColor'));
    fr.putEnumerated(s('mode'),s('blendMode'),s('normal'));fr.putUnitDouble(s('opacity'),s('percentUnit'),100);fr.putUnitDouble(s('size'),s('pixelsUnit'),it.trazo_px);
    color.putDouble(s('red'),it.trazo_rgb[0]);color.putDouble(s('green'),it.trazo_rgb[1]);color.putDouble(s('blue'),it.trazo_rgb[2]);
    fr.putObject(s('color'),s('RGBColor'),color);fx.putObject(s('frameFX'),s('frameFX'),fr);desc.putObject(s('to'),s('layerEffects'),fx);executeAction(s('set'),desc,DialogModes.NO);
}
function inside(x,y,poly){
    var hit=false;
    for(var a=0,b=poly.length-1;a<poly.length;b=a++){
        var u=poly[a],v=poly[b];
        if((u[1]>y)!=(v[1]>y)&&x<(v[0]-u[0])*(y-u[1])/(v[1]-u[1])+u[0])hit=!hit;
    }return hit;
}
function insidePanel(bounds,it){
    if(it.permite_fuera_panel_raw)return true;
    var pad=1;
    return inside(bounds[0]+pad,bounds[1]+pad,it.poligono_panel)&&inside(bounds[2]-pad,bounds[1]+pad,it.poligono_panel)&&inside(bounds[2]-pad,bounds[3]-pad,it.poligono_panel)&&inside(bounds[0]+pad,bounds[3]-pad,it.poligono_panel);
}
function applySymbolFont(doc,layer,it){
    if(!it.rangos_simbolos||!it.rangos_simbolos.length||!it.fuente_simbolos_ps)return;
    doc.activeLayer=layer;
    var r=new ActionReference();r.putIdentifier(s('layer'),layer.id);
    var layerDesc=executeActionGet(r);
    var textKey=layerDesc.getObjectValue(s('textKey'));
    if(!textKey.hasKey(s('textStyleRange')))return;
    var baseList=textKey.getList(s('textStyleRange'));
    if(!baseList.count)return;
    var baseRange=baseList.getObjectValue(0);
    var baseStyle=baseRange.getObjectValue(s('textStyle'));
    var totalTo=baseRange.getInteger(s('to'));
    var newList=new ActionList();
    var cursor=0;
    for(var idx=0;idx<it.rangos_simbolos.length;idx++){
        var seg=it.rangos_simbolos[idx],fromIdx=seg[0],toIdx=seg[1];
        if(fromIdx>cursor){
            var rNormal=new ActionDescriptor();
            rNormal.putInteger(s('from'),cursor);
            rNormal.putInteger(s('to'),fromIdx);
            rNormal.putObject(s('textStyle'),s('textStyle'),baseStyle);
            newList.putObject(s('textStyleRange'),rNormal);
        }
        var symStyle=new ActionDescriptor();
        symStyle.fromStream(baseStyle.toStream());
        symStyle.putString(s('fontPostScriptName'),it.fuente_simbolos_ps);
        if(symStyle.hasKey(s('fontName')))symStyle.putString(s('fontName'),it.fuente_simbolos_ps);
        var rSym=new ActionDescriptor();
        rSym.putInteger(s('from'),fromIdx);
        rSym.putInteger(s('to'),toIdx);
        rSym.putObject(s('textStyle'),s('textStyle'),symStyle);
        newList.putObject(s('textStyleRange'),rSym);
        cursor=toIdx;
    }
    if(cursor<totalTo){
        var rTail=new ActionDescriptor();
        rTail.putInteger(s('from'),cursor);
        rTail.putInteger(s('to'),totalTo);
        rTail.putObject(s('textStyle'),s('textStyle'),baseStyle);
        newList.putObject(s('textStyleRange'),rTail);
    }
    textKey.putList(s('textStyleRange'),newList);
    var setDesc=new ActionDescriptor();
    var targetRef=new ActionReference();
    targetRef.putEnumerated(s('textLayer'),s('ordinal'),s('targetEnum'));
    setDesc.putReference(s('null'),targetRef);
    setDesc.putObject(s('to'),s('textLayer'),textKey);
    executeAction(charIDToTypeID('setd'),setDesc,DialogModes.NO);
}
function auditFontAndStroke(layer,it){
    var actual=layer.textItem.font;
    var hasSym=it.rangos_simbolos&&it.rangos_simbolos.length&&it.fuente_simbolos_ps;
    if(/myriad/i.test(actual)||(actual!==it.font_ps&&!(hasSym&&(actual===it.fuente_simbolos_ps||!actual))))throw new Error('Fuente no permitida: '+it.id+' '+actual);
    var r=new ActionReference();r.putIdentifier(s('layer'),layer.id);
    var layerDesc=executeActionGet(r);
    var descriptor=layerDesc.getObjectValue(s('textKey'));
    if(descriptor.hasKey(s('textStyleRange'))){
        var ranges=descriptor.getList(s('textStyleRange'));
        for(var k=0;k<ranges.count;k++){
            var st=ranges.getObjectValue(k).getObjectValue(s('textStyle'));
            var keys=['fontPostScriptName','fontName'];
            for(var j=0;j<keys.length;j++)if(st.hasKey(s(keys[j]))){
                var name=st.getString(s(keys[j]));
                if(/myriad/i.test(name))throw new Error('Myriad en un fragmento de '+it.id);
                if(keys[j]==='fontPostScriptName'&&name!==it.font_ps&&!(hasSym&&name===it.fuente_simbolos_ps))throw new Error('Fuente sustituida en fragmento: '+it.id+' '+name);
            }
        }
    }
    if(it.trazo_px){
        var fx=layerDesc.getObjectValue(s('layerEffects')).getObjectValue(s('frameFX'));
        if(Math.abs(fx.getUnitDoubleValue(s('size'))-it.trazo_px)>.01)throw new Error('Borde incorrecto '+it.id);
    }
    return actual;
}
try{
    app.preferences.rulerUnits=Units.PIXELS;app.displayDialogs=DialogModes.NO;
    var doc=suppliedDoc||app.open(new File(cfg.input));app.activeDocument=doc;doc.activeChannels=doc.componentChannels;doc.selection.deselect();
    if(new File(cfg.output).exists&&!cfg.reemplazar)throw new Error('El PSD de salida ya existe');
    var docRes=doc.resolution,ptFactor=72/docRes,pxFactor=docRes/72;
    var groups=doc.layerSets.length, layers=[],activeItems=[],review=[];
    // Primera pasada: colocar todo usando coordenadas y cuadros de parrafo.
    for(var i=0;i<cfg.items.length;i++){
        var it=cfg.items[i],box=it.box_composicion||it.box_contenedor,expectedText=it.lineas.join('\r'),layer=null;
        try{
            layer=doc.artLayers.add();layer.kind=LayerKind.TEXT;layer.name=it.id+' | '+it.traduccion_es.substring(0,35);
            if(layer.parent.typename!=='Document')throw new Error('Capa agrupada');
            var ti=layer.textItem;if(ti.kind!==TextType.POINTTEXT)ti.kind=TextType.POINTTEXT;ti.font=it.font_ps;ti.capitalization=TextCase.NORMAL;
            ti.justification=it.alineacion==='izquierda'?Justification.LEFT:(it.alineacion==='derecha'?Justification.RIGHT:Justification.CENTER);ti.useAutoLeading=false;ti.hyphenation=false;
            var color=new SolidColor();color.rgb.red=it.relleno_rgb[0];color.rgb.green=it.relleno_rgb[1];color.rgb.blue=it.relleno_rgb[2];ti.color=color;
            var fs=it.tamano_px,min=it.minimo_px||18,margin=it.margen_revision_px,border=it.trazo_px;
            ti.size=UnitValue(fs*ptFactor,'pt');ti.leading=UnitValue(typeoLeadingPx(it,fs)*ptFactor,'pt');
            ti.position=[UnitValue(300,'px'),UnitValue(400,'px')];ti.contents=expectedText;
            var maxW=box[2]-box[0]-2*margin-2*border,maxH=box[3]-box[1]-2*margin-2*border,fit=false,h=0;
            for(var n=0;n<80;n++){
                if(n>0){ti.size=UnitValue(fs*ptFactor,'pt');ti.leading=UnitValue(typeoLeadingPx(it,fs)*ptFactor,'pt');}
                var b=bounds(layer),w=b[2]-b[0];h=b[3]-b[1];
                if(w<=maxW&&h<=maxH){fit=true;break;}
                var fitted=typeoFitSize(fs,min,w,h,maxW,maxH);
                if(fitted===null)break;fs=fitted;
            }
            if(!fit)throw new Error('No cabe '+it.id);
            ti.kind=TextType.PARAGRAPHTEXT;ti.width=UnitValue(maxW+2,'px');
            ti.height=UnitValue(Math.max(maxH+2,h+fs*.9),'px');
            ti.position=[UnitValue((box[0]+box[2]-maxW)/2,'px'),UnitValue(box[1]+margin,'px')];
            if(ti.contents!==expectedText)ti.contents=expectedText;
            if(ti.font!==it.font_ps)ti.font=it.font_ps;
            applySymbolFont(doc,layer,it);
            stroke(layer,it);
            layers.push(layer);activeItems.push(it);say('COLOCADO '+it.id+' | '+fs+'px | '+it.font_ps+' | PARAGRAPHTEXT | HORIZONTAL');
        }catch(itemErr1){
            if(layer){try{layer.remove();}catch(eRem1){}}
            say('OMITIDO '+it.id+' | '+itemErr1.message);
        }
    }
    // Segunda pasada: medir el texto renderizado, corregir centro y auditar cada fragmento.
    for(var i=0;i<layers.length;i++){
        var layer=layers[i],it=activeItems[i],box=it.box_composicion||it.box_contenedor,ti=layer.textItem;
        try{
            var before=bounds(layer),cx=(box[0]+box[2])/2,cy=(box[1]+box[3])/2;
            var maxW=box[2]-box[0]-2*it.margen_revision_px,maxH=box[3]-box[1]-2*it.margen_revision_px;
            var fs=ti.size.as('pt')*pxFactor,b=before;
            for(var n=0;n<60;n++){
                if(n>0){
                    ti.size=UnitValue(fs*ptFactor,'pt');ti.leading=UnitValue(typeoLeadingPx(it,fs)*ptFactor,'pt');
                    b=bounds(layer);
                }
                if(b[2]-b[0]<=maxW&&b[3]-b[1]<=maxH)break;
                var fitted=typeoFitSize(fs,it.minimo_px||18,b[2]-b[0],b[3]-b[1],maxW,maxH);
                if(fitted===null)throw new Error('Revision sin ajuste seguro '+it.id);fs=fitted;
            }
            var targetX=it.alineacion==='izquierda'?box[0]+it.margen_revision_px+it.trazo_px:(it.alineacion==='derecha'?box[2]-it.margen_revision_px-it.trazo_px-(b[2]-b[0]):cx-(b[2]-b[0])/2);
            var dx=targetX-b[0],dy=cy-(b[1]+b[3])/2;
            layer.translate(UnitValue(dx,'px'),UnitValue(dy,'px'));
            var after=bounds(layer),errorX=Math.abs(after[0]-targetX),errorY=Math.abs((after[1]+after[3])/2-cy);
            if(errorX>1.1||errorY>1.1)throw new Error('Centro incorrecto '+it.id);
            if(after[0]<box[0]-1||after[1]<box[1]-1||after[2]>box[2]+1||after[3]>box[3]+1)throw new Error('Desborde '+it.id);
            var angle=it.rotacion||0,rad=angle*Math.PI/180,co=Math.cos(rad),si=Math.sin(rad);
            var corners=[[after[0],after[1]],[after[2],after[1]],[after[2],after[3]],[after[0],after[3]]];
            if(angle){
                var acx=(after[0]+after[2])/2,acy=(after[1]+after[3])/2;
                layer.rotate(angle,AnchorPosition.MIDDLECENTER);
                var rotatedCx=cx+co*(acx-cx)-si*(acy-cy),rotatedCy=cy+si*(acx-cx)+co*(acy-cy);
                layer.translate(UnitValue(rotatedCx-acx,'px'),UnitValue(rotatedCy-acy,'px'));
                for(var ci=0;ci<corners.length;ci++){var px=corners[ci][0]-cx,py=corners[ci][1]-cy;corners[ci]=[cx+co*px-si*py,cy+si*px+co*py];}
                after=bounds(layer);
                if(!it.permite_fuera_panel_raw)for(var ci=0;ci<corners.length;ci++)if(!inside(corners[ci][0],corners[ci][1],it.poligono_panel))throw new Error('Texto rotado fuera del panel '+it.id);
            }
            if(!angle&&!insidePanel(after,it))throw new Error('Texto fuera de panel sin excepcion RAW: '+it.id);
            for(var protectedIndex=0;protectedIndex<(cfg.regiones_protegidas||[]).length;protectedIndex++){
                if(intersectsProtected(after,cfg.regiones_protegidas[protectedIndex]))throw new Error('Texto invade sonido, numero o signo protegido: '+it.id);
            }
            if(ti.kind!==TextType.PARAGRAPHTEXT||layer.parent.typename!=='Document')throw new Error('Tipo de capa incorrecto');
            if(ti.contents!==it.lineas.join('\r'))throw new Error('Contenido alterado '+it.id+' real '+encodeURI(ti.contents)+' esperado '+encodeURI(it.lineas.join('\r')));
            applySymbolFont(doc,layer,it);
            var actualFont=auditFontAndStroke(layer,it);

            review.push({id:it.id,before:before,after:after,dx:dx,dy:dy,centerErrorPx:[errorX,errorY],font:actualFont,sizePx:fs,leadingPx:ti.leading.as('pt')*pxFactor,rotation:angle,corners:corners,editable:true});
            say('REVISADO '+it.id+' | CENTRADO_REAL | '+actualFont+' | '+fs+'px | dx '+dx+' | dy '+dy+' | SIN_MYRIAD | PANEL_VALIDADO');
        }catch(itemErr2){
            try{layer.remove();}catch(eRem2){}
            say('OMITIDO '+it.id+' | '+itemErr2.message);
        }
    }
    if(doc.layerSets.length!==groups)throw new Error('Se creo carpeta de typeo');
    var jsonFile=new File(cfg.revision_log);jsonFile.encoding='UTF8';jsonFile.open('w');
    // ExtendScript no garantiza JSON.stringify en todas las instalaciones.
    var lines=['['];for(var r=0;r<review.length;r++){
        var q=review[r];lines.push((r?',':'')+'{"id":"'+q.id+'","before":['+q.before.join(',')+'],"after":['+q.after.join(',')+'],"dx":'+q.dx+',"dy":'+q.dy+',"centerErrorPx":['+q.centerErrorPx.join(',')+'],"font":"'+q.font+'","sizePx":'+q.sizePx+',"leadingPx":'+q.leadingPx+',"rotation":'+q.rotation+',"corners":[['+q.corners[0].join(',')+'],['+q.corners[1].join(',')+'],['+q.corners[2].join(',')+'],['+q.corners[3].join(',')+']],"editable":true}');
    }lines.push(']');jsonFile.write(lines.join('\n'));jsonFile.close();
    if(cfg.on_stage)cfg.on_stage('typeo_render_complete');
    if(beforeSave)beforeSave(doc);
    if(cfg.on_stage)cfg.on_stage('psd_save_start');
    if(cfg.revision_final_existente){
        if(doc.fullName.fsName.toLowerCase()!==new File(cfg.output).fsName.toLowerCase())throw new Error('La revision no apunta al PSD final abierto');
        doc.save();
    }else{
        activateFinalDocument(doc,cfg.output,cfg.permitir_reemplazo_abierto===true);
        var psd=new PhotoshopSaveOptions();psd.layers=true;doc.saveAs(new File(cfg.output),psd,false,Extension.LOWERCASE);
    }
    if(cfg.on_stage)cfg.on_stage('psd_save_complete');
    if(cfg.preview){try{
        var sfw=new ExportOptionsSaveForWeb();
        sfw.format=SaveDocumentType.JPEG;
        sfw.quality=80;
        doc.exportDocument(new File(cfg.preview),ExportType.SAVEFORWEB,sfw);
    }catch(eSfw){
        var temp=null;
        try{temp=doc.duplicate();temp.flatten();var jpg=new JPEGSaveOptions();jpg.quality=10;temp.saveAs(new File(cfg.preview),jpg,true,Extension.LOWERCASE);}
        finally{if(temp)temp.close(SaveOptions.DONOTSAVECHANGES);app.activeDocument=doc;}
    }}

    say('EXITO | '+layers.length+' CAPAS_SUELTAS | DOS_PASADAS | TODO_HORIZONTAL | SIN_MYRIAD | PANELES_RAW_VALIDOS');
    var done=new File(cfg.done);done.open('w');done.write('EXITO');done.close();
    result('complete','Texto, paneles, fuentes y bordes verificados');return true;
}catch(e){say('ERROR '+e.message+' | linea '+e.line);result('error',e.message+' | linea '+e.line);return false;}
finally{app.preferences.rulerUnits=units;app.displayDialogs=dialogs;if(smartQuotes!==undefined){try{app.preferences.useSmartQuotes=smartQuotes;}catch(ignoreRestore){}}if(maxCompat!==undefined){try{app.preferences.maximizeCompatibility=maxCompat;}catch(ignoreCompatRestore){}}log.close();}
}
