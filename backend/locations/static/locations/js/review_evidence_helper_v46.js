/* Workplace Insights v46 — staff-only provenance assistance.
 * NEVER invents a source URL or asserts a location has been verified.
 */
(function () {
 'use strict';
 function checkUrl(raw) {
  try {
   const u = new URL(String(raw || '').trim());
   return u.protocol === 'https:' && !!u.hostname && !u.username && !u.password;
  } catch (_) { return false; }
 }
 function compose({decision, evidence, address, latitude, longitude, confirmed}) {
  if (decision !== 'verified')
   return {ok:false, message:'متن خودکار فعلاً فقط برای گزینه «مکان تأیید شد» قابل استفاده است؛ برای رد یا لغو تأیید، دلیل واقعی خودتان را بنویسید.'};
  if (!address || address.trim().length < 8)
   return {ok:false, message:'ابتدا نقطه را روی نقشه انتخاب کنید و نشانی را بررسی کنید.'};
  const lat = Number(latitude), lng = Number(longitude);
  if (!String(latitude||'').trim() || !String(longitude||'').trim() ||
      !Number.isFinite(lat) || !Number.isFinite(lng) || Math.abs(lat) > 90 || Math.abs(lng) > 180)
   return {ok:false, message:'ابتدا موقعیت صحیح را روی نقشه انتخاب کنید.'};
  if (!checkUrl(evidence))
   return {ok:false, message:'لینک HTTPS صفحه‌ای را وارد کنید که نشانی دفتر شرکت در آن درج شده است؛ لینک نقشه به‌تنهایی مدرک نیست.'};
  if (!confirmed)
   return {ok:false, message:'ابتدا صفحه مدرک را باز کنید و فقط در صورت تطبیق واقعی نشانی، کادر تأیید را علامت بزنید.'};
  return {ok:true, text:'صفحه مدرک پیوست بررسی شد و نشانی دفتر شرکت در آن با موقعیت انتخاب‌شده روی نقشه تطبیق داده شد. تأیید مکان بر اساس بررسی دستی انجام گرفت.'};
 }
 // Exposed only for deterministic offline tests, never used for data submission.
 if (typeof window !== 'undefined') window.wiEvidenceHelperV46={checkUrl,compose};
 function init(){
  const root=document.getElementById('wi-location-picker');
  const e=document.getElementById('id_evidence_url'), r=document.getElementById('id_rationale'),
   d=document.getElementById('id_decision'), a=document.getElementById('id_address'),
   lat=document.getElementById('id_latitude'), lon=document.getElementById('id_longitude');
  if(!root||!e||!r||!d||!a||!lat||!lon)return;
  const pane=document.createElement('section');pane.dir='rtl';pane.className='wi-review-helper-v46';
  pane.style.cssText='padding:12px 16px;margin:12px 0;border:1px solid var(--hairline-color,#ddd);border-radius:6px;line-height:1.9';
  const header=document.createElement('strong');header.textContent='راهنمای ساده تأیید مکان';pane.appendChild(header);
  const help=document.createElement('p');help.textContent='Evidence URL یعنی لینک صفحه‌ای که نشانی رسمی دفتر در آن دیده می‌شود (مثلاً «تماس با ما»). Rationale یعنی علت تصمیم شما؛ می‌توانیم متن آن را بعد از بررسی واقعی منبع خودکار بسازیم.';
  pane.appendChild(help);
  const search=document.createElement('button');search.type='button';search.className='button';
  search.textContent='جست‌وجوی صفحه تماس با ما شرکت';pane.appendChild(search);
  const searchStatus=document.createElement('span');searchStatus.style.marginInlineStart='8px';pane.appendChild(searchStatus);
  search.addEventListener('click',()=>{
   const company=document.getElementById('id_company');
   const selected=company && company.selectedOptions && company.selectedOptions[0];
   const selectedText=selected && selected.value ? selected.textContent : '';
   const select2=document.querySelector('#select2-id_company-container');
   const text=(selectedText || (select2 && select2.textContent) || '').trim();
   if(!text || /انتخاب|select|---------/i.test(text)){
    searchStatus.textContent='ابتدا شرکت را انتخاب کنید.';return;
   }
   searchStatus.textContent='در صفحه جست‌وجو، نشانی دفتر و اعتبار لینک را بررسی کنید.';
   const target='https://www.google.com/search?q='+encodeURIComponent(text+' تماس با ما آدرس دفتر رسمی');
   window.open(target,'_blank','noopener,noreferrer');
  });
  const evidenceHelp=document.createElement('p');
  evidenceHelp.textContent='لینک نتیجه جست‌وجو را کپی نکنید؛ لینک مستقیم صفحه‌ای را بگذارید که واقعاً آدرس شرکت در آن ثبت شده است.';
  pane.appendChild(evidenceHelp);
  const wrap=document.createElement('label');wrap.style.cssText='display:block;margin:10px 0';
  const checked=document.createElement('input');checked.type='checkbox';checked.style.marginInlineEnd='7px';
  wrap.append(checked,document.createTextNode('من صفحه مدرک را باز کردم و نشانی شرکت را با پین نقشه تطبیق دادم.'));
  pane.appendChild(wrap);
  const button=document.createElement('button');button.type='button';button.className='button';button.textContent='پرکردن خودکار توضیح (Rationale)';pane.appendChild(button);
  const notice=document.createElement('p');notice.setAttribute('role','status');notice.style.marginTop='8px';pane.appendChild(notice);
  const form=e.closest('.form-row') || e.parentElement;
  if(form && form.parentElement)form.insertAdjacentElement('afterend',pane);
  else root.appendChild(pane);
  let autoWritten='';
  function invalidate(message){
   if(checked.checked){
    checked.checked=false;notice.textContent=message;
    if(autoWritten && r.value===autoWritten){r.value='';r.dispatchEvent(new Event('change',{bubbles:true}));}
    autoWritten='';
   }
  }
  function fill(askToReplace){
   const answer=compose({decision:d.value,evidence:e.value,address:a.value,
    latitude:lat.value,longitude:lon.value,confirmed:checked.checked});
   if(!answer.ok){notice.textContent=answer.message;return;}
   if(r.value.trim()){
    if(!askToReplace)return;
    if(!window.confirm('متن فعلی Rationale جایگزین شود؟'))return;
   }
   r.value=answer.text;autoWritten=answer.text;r.dispatchEvent(new Event('change',{bubbles:true}));
   notice.textContent='توضیح پیشنهادی تکمیل شد. در صورت نیاز آن را ویرایش کنید.';
  }
  button.addEventListener('click',()=>fill(true));
  checked.addEventListener('change',()=>{
   if(checked.checked)fill(false);
   else {if(autoWritten && r.value===autoWritten){r.value='';r.dispatchEvent(new Event('change',{bubbles:true}));}
    autoWritten='';notice.textContent='تأیید تطبیق برداشته شد؛ توضیح خودکار پاک شد.';}
  });
  e.addEventListener('input',()=>invalidate('لینک مدرک تغییر کرد؛ دوباره تطبیق را تأیید کنید.'));
  a.addEventListener('input',()=>invalidate('نشانی تغییر کرد؛ دوباره تطبیق را تأیید کنید.'));
  a.addEventListener('change',()=>invalidate('نشانی تغییر کرد؛ دوباره تطبیق را تأیید کنید.'));
  lat.addEventListener('change',()=>invalidate('مکان تغییر کرد؛ دوباره تطبیق را تأیید کنید.'));
  lon.addEventListener('change',()=>invalidate('مکان تغییر کرد؛ دوباره تطبیق را تأیید کنید.'));
  d.addEventListener('change',()=>invalidate('نتیجه بررسی تغییر کرد؛ دوباره تطبیق را تأیید کنید.'));
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);
 else init();
})();
