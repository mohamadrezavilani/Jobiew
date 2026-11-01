(function(){'use strict';
const nodes=Array.from(document.querySelectorAll('.wi-company-cover-v27[data-company-photo-id]'));
if(!nodes.length)return;
const cache=new Map();
function show(node,rec){
  if(!rec)return;
  const prefix=node.getAttribute('data-static-prefix')||'/static/';
  const initial=node.querySelector('.wi-v27-initial');
  const credit=node.querySelector('.wi-v27-photo-credit');
  const img=document.createElement('img');
  img.className='wi-v27-real-photo '+(rec.image_kind==='photo'||rec.image_kind==='official_web_image'?'wi-v27-wide':'wi-v27-logo');
  img.alt=rec.origin==='user_supplied'?'تصویر ارسالی شرکت توسن':'تصویر یا نشان برگرفته از وب‌سایت شرکت '+rec.company_name;
  img.loading='eager';img.decoding='async';img.referrerPolicy='no-referrer';
  const sources=[];
  if(rec.image)sources.push(prefix.replace(/\/$/,'')+'/'+rec.image);
  if(rec.official_domain)sources.push('https://www.google.com/s2/favicons?domain='+encodeURIComponent(rec.official_domain)+'&sz=256');
  let index=0;
  img.onerror=function(){index++;if(index<sources.length){img.className='wi-v27-real-photo wi-v27-logo';img.src=sources[index];}else{img.remove();if(credit)credit.hidden=true;}};
  img.onload=function(){node.classList.add('wi-v27-loaded');node.classList.toggle('wi-v27-has-photo',img.classList.contains('wi-v27-wide'));if(initial)initial.style.display='none';if(credit){credit.hidden=false;credit.textContent=rec.origin==='user_supplied'?'تصویر ارسالی توسن':(img.classList.contains('wi-v27-logo')?'نشان وب‌سایت شرکت':'تصویر وب‌سایت شرکت');}};
  if(sources.length){node.appendChild(img);img.src=sources[0];}
}
for(const node of nodes){const url=node.getAttribute('data-photo-manifest');if(!cache.has(url))cache.set(url,fetch(url,{cache:'no-cache'}).then(r=>{if(!r.ok)throw new Error('manifest '+r.status);return r.json();}).catch(()=>({companies:{}})));
cache.get(url).then(m=>show(node,(m.companies||{})[node.getAttribute('data-company-photo-id')]));}
})();