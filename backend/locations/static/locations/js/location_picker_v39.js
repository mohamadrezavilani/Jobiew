/* Workplace Insights v41: MapLibre/OpenFreeMap through staff-only Django proxy.
   OSMF's blocked raster service is not requested. */
(function(){
 'use strict';
 function init(){
  const root=document.getElementById('wi-location-picker');
  if(!root)return;
  const lat=document.getElementById('id_latitude'),lng=document.getElementById('id_longitude');
  const status=document.getElementById('wi-location-picker-status');
  const search=document.getElementById('wi-location-search');
  const searchBtn=document.getElementById('wi-location-search-button');
  const clearBtn=document.getElementById('wi-location-clear-button');
  const results=document.getElementById('wi-location-search-results');
  // v45: geocoder is staff-only; data suggests a nearby OSM address, not a verified company office.
  const addressField=document.getElementById('id_address');
  const addressPanel=document.createElement('div');
  addressPanel.className='wi-reverse-address-panel';
  addressPanel.setAttribute('dir','rtl');
  const reverseStatus=document.createElement('p');
  reverseStatus.setAttribute('role','status');
  reverseStatus.textContent='پس از انتخاب نقطه، نشانی تقریبی این مکان پیشنهاد می‌شود.';
  const reverseSuggestion=document.createElement('p');
  const useSuggestion=document.createElement('button');
  useSuggestion.type='button';useSuggestion.className='button';
  useSuggestion.textContent='استفاده از آدرس پیشنهادی';
  useSuggestion.hidden=true;
  const reverseAttribution=document.createElement('small');
  reverseAttribution.textContent=' © OpenStreetMap contributors — Nominatim؛ نشانی پیشنهادی نیاز به تأیید دارد.';
  addressPanel.append(reverseStatus,reverseSuggestion,useSuggestion,reverseAttribution);
  status.after(addressPanel);
  let userEditedAddress=!!(addressField && addressField.value.trim());
  let lastAutoAddress='',currentSuggestion='',reverseTimer=null,reverseSerial=0;
  if(addressField)addressField.addEventListener('input',()=>{userEditedAddress=true;});
  function applySuggestedAddress(value){
   if(!addressField||!value)return;
   addressField.value=value;
   addressField.dispatchEvent(new Event('change',{bubbles:true}));
   lastAutoAddress=value;userEditedAddress=false;
   reverseStatus.textContent='آدرس تقریبی وارد شد؛ لطفاً صحت نشانی دفتر شرکت را بررسی و اصلاح کنید.';
   useSuggestion.hidden=true;
  }
  useSuggestion.addEventListener('click',()=>applySuggestedAddress(currentSuggestion));
  function lookupSelectedPoint(coords){
   reverseSerial++;
   const serial=reverseSerial;
   if(reverseTimer!==null)clearTimeout(reverseTimer);
   currentSuggestion='';reverseSuggestion.textContent='';useSuggestion.hidden=true;
   reverseStatus.textContent='در حال پیشنهاد نشانی برای نقطه انتخاب‌شده…';
   reverseTimer=setTimeout(async()=>{
    try{
     const query='?lat='+encodeURIComponent(coords[1].toFixed(6))+'&lon='+encodeURIComponent(coords[0].toFixed(6));
     const response=await fetch('/admin-location-reverse/'+query,{credentials:'same-origin'});
     const data=await response.json();
     if(serial!==reverseSerial)return;
     if(!response.ok||!data||typeof data.address!=='string'){
      reverseStatus.textContent=(data && data.message)||'پیشنهاد آدرس در دسترس نیست؛ آدرس را دستی وارد کنید.';
      return;
     }
     currentSuggestion=data.address;
     if(addressField && (!userEditedAddress || !addressField.value.trim() ||
        (lastAutoAddress && addressField.value===lastAutoAddress))){
      applySuggestedAddress(currentSuggestion);
     }else{
      reverseSuggestion.textContent='نشانی پیشنهادی: '+currentSuggestion;
      reverseStatus.textContent='آدرس دستی شما حفظ شد. برای جایگزینی از دکمه زیر استفاده کنید.';
      useSuggestion.hidden=false;
     }
    }catch(e){
     if(serial===reverseSerial)reverseStatus.textContent='پیشنهاد آدرس در دسترس نیست؛ آدرس را دستی وارد کنید.';
    }
   },650);
  }
  if(!lat||!lng){status.textContent='فیلدهای مختصات پیدا نشدند.';return;}
  if(!window.maplibregl){
   status.textContent='کتابخانه MapLibre از CDN بارگیری نشده است؛ ابتدا اتصال مرورگر به unpkg.com را بررسی کنید.';
   const row=document.createElement('p');row.textContent='اشکال از Tile یا پروکسی نیست؛ فایل maplibre-gl.js در مرورگر اجرا نشده است.';
   status.after(row);return;
  }
  if(!window.WebGLRenderingContext){
   status.textContent='مرورگر از WebGL پشتیبانی نمی‌کند یا آن را غیرفعال کرده است.';return;
  }
  const prefix='/admin-map-assets/';
  // MapLibre's worker requires fully-qualified URLs for sprites and vector tiles.
  const absoluteProxyBase=new URL(prefix,window.location.origin).href;
  let marker=null,lastSearch=0;
  let map;
  try{map=new maplibregl.Map({
   container:'wi-location-map',
   style:absoluteProxyBase+'styles/liberty',
   center:[51.3890,35.6892],zoom:10.5,
   transformRequest:function(url){
    if(typeof url!=='string')return {url:url};
    try{
     const u=new URL(url,window.location.origin);
     // Fallback for provider links that were not rewritten in Style/TileJSON.
     if(u.hostname==='tiles.openfreemap.org' && u.protocol==='https:' &&
        !u.username && !u.password && !u.search && !u.hash)
      return {url:absoluteProxyBase+u.pathname.replace(/^\//,'')};
     // Also normalize root-relative proxied URLs already emitted by older JSON.
     if(u.origin===window.location.origin && u.pathname.startsWith(prefix))
      return {url:u.href};
    }catch(e){}
    return {url:url};
   },
  });}
  catch(err){status.textContent='ساخت نقشه در مرورگر ناموفق بود (WebGL یا MapLibre). جزئیات را در Console بررسی کنید.';return;}
  map.addControl(new maplibregl.NavigationControl(),'top-left');
  let mapErrorCount=0;
  map.on('error',function(e){
   mapErrorCount++;
   const err=e && e.error;
   const rawUrl=err && (err.url || (err.request && err.request.url));
   let resource='نامشخص';
   try {
    const u = rawUrl ? new URL(rawUrl,location.href) : null;
    if(u && u.origin===location.origin)resource=u.pathname.slice(0,140);
    else if(u)resource='منبع بیرونی ('+u.hostname.slice(0,70)+')';
   } catch (_) {}
   status.textContent='خطای بارگذاری منبع نقشه ('+mapErrorCount+'): '+resource+'. دستور diagnose_map_v41 را اجرا کنید یا تب Network مرورگر را ببینید.';
   console.error('MapLibre actual error:', err, 'resource:', resource);
  });
  map.on('load',()=>{if(!mapErrorCount)status.textContent='لایه‌های نقشه بارگذاری شدند. روی نقشه کلیک کنید تا مکان انتخاب شود.';});
  map.on('idle',()=>{if(!mapErrorCount)status.textContent='نقشه آماده است؛ برای انتخاب محل روی نقشه کلیک کنید.';});
  const diagnostic=document.createElement('button');diagnostic.type='button';
  diagnostic.className='button'; diagnostic.textContent='بررسی فایل‌های نقشه';
  status.after(diagnostic);
  diagnostic.addEventListener('click',async()=>{
   diagnostic.disabled=true;
   const targets=['styles/liberty','planet','sprites/ofm_f384/ofm.json'];
   const lines=[];
   for(const path of targets){
    try{
     const resp=await fetch(prefix+path,{credentials:'same-origin',cache:'no-store'});
     const upstream=resp.headers.get('X-WI-Map-Upstream-Status');
     lines.push(path+': '+resp.status+(upstream?' (upstream '+upstream+')':''));
    }catch(e){lines.push(path+': خطای اتصال در مرورگر');}
   }
   status.textContent='نتیجه دریافت منابع: '+lines.join(' | ');
   diagnostic.disabled=false;
  });
  function readCoords(){
   const a=lat.value.trim(),b=lng.value.trim();
   if(!a||!b)return null;
   const la=Number(a),lo=Number(b);
   return Number.isFinite(la)&&Number.isFinite(lo)&&Math.abs(la)<=90&&Math.abs(lo)<=180?[lo,la]:null;
  }
  function put(coords,save){
   if(!coords || !Number.isFinite(coords[0]) || !Number.isFinite(coords[1]) || Math.abs(coords[0])>180 || Math.abs(coords[1])>90)return;
   if(marker)marker.setLngLat(coords);
   else{
    marker=new maplibregl.Marker({draggable:true}).setLngLat(coords).addTo(map);
    marker.on('dragend',()=>put(marker.getLngLat().toArray(),true));
   }
   if(save){
    lat.value=coords[1].toFixed(6);lng.value=coords[0].toFixed(6);
    lat.dispatchEvent(new Event('change',{bubbles:true}));lng.dispatchEvent(new Event('change',{bubbles:true}));
   }
   if(save)lookupSelectedPoint(coords);
   status.textContent='مکان انتخاب شد؛ برای اصلاح، پین را جابه‌جا کنید یا دوباره روی نقشه کلیک کنید.';
  }
  const existing=readCoords();
  if(existing){put(existing,false);map.jumpTo({center:existing,zoom:15});}
  else status.textContent='روی نقشه کلیک کنید تا محل شرکت مشخص شود.';
  map.on('click',e=>put([e.lngLat.lng,e.lngLat.lat],true));
  function fromFields(){const p=readCoords();if(p){put(p,false);map.panTo(p);}}
  lat.addEventListener('change',fromFields);lng.addEventListener('change',fromFields);
  clearBtn.addEventListener('click',function(){
   reverseSerial++;
   if(reverseTimer!==null)clearTimeout(reverseTimer);
   currentSuggestion='';reverseSuggestion.textContent='';useSuggestion.hidden=true;
   reverseStatus.textContent='نقطه پاک شد؛ برای نشانی جدید روی نقشه کلیک کنید.';
   if(addressField && lastAutoAddress && addressField.value===lastAutoAddress){
    addressField.value='';addressField.dispatchEvent(new Event('change',{bubbles:true}));
    lastAutoAddress='';userEditedAddress=false;
   }
   lat.value='';lng.value='';results.replaceChildren();
   if(marker){marker.remove();marker=null;}
   status.textContent='انتخاب پاک شد.';
  });
  searchBtn.addEventListener('click',async function(){
   const q=search.value.trim();results.replaceChildren();
   if(q.length<3||q.length>180){status.textContent='عبارت جست‌وجو باید ۳ تا ۱۸۰ کاراکتر باشد.';return;}
   if(Date.now()-lastSearch<1500){status.textContent='برای جست‌وجوی بعدی کمی صبر کنید.';return;}
   lastSearch=Date.now();searchBtn.disabled=true;
   status.textContent='در حال جست‌وجو…';
   try{
    // Geocoding is separate from map tiles; search is optional and explicitly initiated.
    const u='https://nominatim.openstreetmap.org/search?format=jsonv2&limit=5&countrycodes=ir&q='+encodeURIComponent(q);
    const r=await fetch(u,{headers:{Accept:'application/json'}});
    if(!r.ok)throw new Error('search_error');
    const rows=await r.json();
    if(!Array.isArray(rows)||!rows.length){status.textContent='نتیجه‌ای پیدا نشد؛ محل را مستقیم روی نقشه انتخاب کنید.';return;}
    rows.slice(0,5).forEach(item=>{
     const la=Number(item.lat),lo=Number(item.lon);
     if(!Number.isFinite(la)||!Number.isFinite(lo))return;
     const btn=document.createElement('button');btn.type='button';btn.className='button';btn.textContent=String(item.display_name||'مکان');
     btn.addEventListener('click',function(){map.flyTo({center:[lo,la],zoom:15});put([lo,la],true);results.replaceChildren();});
     results.appendChild(btn);
    });
    status.textContent='یکی از نتایج را انتخاب کنید یا روی نقشه کلیک کنید.';
   }catch(e){status.textContent='جست‌وجو در دسترس نیست؛ محل را روی نقشه انتخاب کنید.';}
   finally{searchBtn.disabled=false;}
  });
  search.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();searchBtn.click();}});
  setTimeout(()=>map.resize(),250);
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
