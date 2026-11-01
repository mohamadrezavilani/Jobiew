/* Workplace Insights v23 – UI only. No network requests, no persistence, no publication of private data. */
(function () {
  'use strict';
  const numerals = '۰۱۲۳۴۵۶۷۸۹';
  const fa = value => String(value).replace(/[0-9]/g, c => numerals[Number(c)]).replace(/\./g, '٫');
  const fmt = value => Number.isFinite(Number(value)) ? fa(Number(value).toFixed(2)) : '—';
  const text = (parent, str, className) => {
    const span = document.createElement('span');
    if (className) span.className = className;
    span.textContent = String(str);
    parent.appendChild(span);
    return span;
  };
  const publicNames = [
    'تعادل کار و زندگی و تناسب حجم کار',
    'کیفیت مدیریت و محیط کاری',
    'رشد و توسعه فردی و حرفه‌ای',
    'جبران خدمات و فرهنگ قدردانی',
    'ثبات و امنیت شغلی'
  ];
  const shortLabels = [
    ['تعادل کار و زندگی', 'و تناسب حجم کار'],
    ['کیفیت مدیریت', 'و محیط کاری'],
    ['رشد فردی', 'و حرفه‌ای'],
    ['جبران خدمات', 'و قدردانی'],
    ['ثبات و امنیت', 'شغلی']
  ];
  const chart = document.querySelector('.wi-radar');
  if (!chart) return;
  const source = document.getElementById('wi-criteria-v23-data');
  let criteria = publicNames.map(label => ({label, mean_provisional:null, score:null}));
  if (source) {
    try {
      const parsed = JSON.parse(source.textContent);
      if (Array.isArray(parsed) && parsed.length === 5) criteria = parsed;
    } catch (e) { /* Continue with a safe empty chart, never fabricated scores. */ }
  }
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const grid = chart.querySelector('[data-radar-grid]');
  const plot = chart.querySelector('[data-radar-plot]');
  const centerX = 260, centerY = 242, radius = 136, count = 5;
  const point = (index, value) => {
    const angle = (-Math.PI / 2) + index * (2 * Math.PI / count);
    return [centerX + Math.cos(angle) * (radius * value / 10), centerY + Math.sin(angle) * (radius * value / 10)];
  };
  const make = (kind, attributes, container) => {
    const node = document.createElementNS(SVG_NS, kind);
    for (const [k, v] of Object.entries(attributes)) node.setAttribute(k, String(v));
    container.appendChild(node);
    return node;
  };
  const chartLabels = criteria.map((x, i) => shortLabels[i]);
  for (let level=2; level<=10; level+=2) {
    make('polygon', {points:criteria.map((_, i) => point(i, level).join(',')).join(' ')}, grid);
  }
  for (let i=0; i<count; i++) {
    const [x, y] = point(i, 10);
    make('line', {x1:centerX, y1:centerY, x2:x, y2:y}, grid);
    const labelPoint = point(i, 12.1);
    const xLabel = Math.min(473, Math.max(47, labelPoint[0]));
    const yLabel = Math.min(449, Math.max(25, labelPoint[1]));
    const anchor = Math.abs(xLabel-centerX)<15 ? 'middle' : xLabel>centerX ? 'start' : 'end';
    const label = make('text', {x:xLabel, y:yLabel-8, 'text-anchor':anchor}, grid);
    chartLabels[i].forEach((part, j) => {
      const sub = make('tspan', {x:xLabel, dy:j === 0 ? 0 : 17}, label);
      sub.textContent = part;
    });
    if (chart.dataset.chartMode === 'provisional') {
      const score = criteria[i].mean_provisional;
      if (typeof score === 'number' && score >= 1 && score <= 10) {
        const bottom = make('tspan', {x:xLabel, dy:21, fill:'#245ed6'}, label);
        bottom.textContent = fmt(score);
      }
    }
  }
  function drawSeries(field, isVerified) {
    const values = criteria.map(item => typeof item[field] === 'number' && item[field] >= 1 && item[field] <= 10 ? item[field] : null);
    const good = values.filter(v => v !== null).length;
    if (!good) return;
    const className = isVerified ? 'wi-verified-shape' : 'wi-provisional-shape';
    if (good === 5) {
      make('polygon', {points:values.map((v,i) => point(i,v).join(',')).join(' '), class:className}, plot);
    } else {
      // Connect adjacent known axes only: do not draw a misleading complete pentagon.
      for (let i=0;i<5;i++) {
        const j=(i+1)%5;
        if(values[i] !== null && values[j] !== null) {
          make('polyline',{points:point(i,values[i]).join(',')+' '+point(j,values[j]).join(','),class:className}, plot);
        }
      }
    }
    for(let i=0;i<5;i++) {
      const value=values[i];
      if(value === null) continue;
      const [cx,cy]=point(i,value);
      const circle=make('circle',{cx,cy,r:isVerified?5.5:6.7,tabindex:'0',role:'button',class:className,'aria-label':criteria[i].label+': '+fmt(value)+' از ۱۰'},plot);
      const title=make('title',{},circle);
      title.textContent=criteria[i].label+': '+fmt(value)+' از ۱۰';
      const select=() => {const b=document.querySelector('[data-criterion-index="'+i+'"]');if(b)b.click();};
      circle.addEventListener('click',select);
      circle.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();select();}});
    }
  }
  if (chart.dataset.chartMode === 'provisional' && source) {
    drawSeries('mean_provisional', false);
    drawSeries('score', true);
  }
  const controls=[...document.querySelectorAll('[data-criterion-index]')];
  const details=document.getElementById('wi-criterion-detail');
  if (source && details && controls.length === 5) {
    function show(index) {
      controls.forEach((button,i)=>button.setAttribute('aria-pressed',String(i===index)));
      const value=criteria[index];
      details.replaceChildren();
      const rows=[
        ['معیار', value.label],
        ['میانگین پیشنهادی AI', typeof value.mean_provisional === 'number' ? fmt(value.mean_provisional)+' از ۱۰' : 'بدون امتیاز'],
        ['تعداد نظرات مؤثر',fa(value.n_provisional_used || 0)],
        ['بدون امتیاز / فاقد شواهد کافی',fa(value.n_provisional_abstentions || 0)],
        ['کمترین و بیشترین نمره', typeof value.min_provisional === 'number' && typeof value.max_provisional === 'number' ? fmt(value.min_provisional)+' تا '+fmt(value.max_provisional) : '—'],
        ['اجرای تکراری مبهمِ کنارگذاشته‌شده', fa(value.n_ambiguous_run_rows || 0)],
        ['متن تکراری کنارگذاشته‌شده',fa(value.n_content_duplicates_excluded || 0)],
        ['میانگین پژوهشیِ تأییدشده',typeof value.score === 'number' ? fmt(value.score)+' از ۱۰' : 'فاقد داده تأییدشده کافی'],
        ['تعداد شواهد مستقل تأییدشده',fa(value.n_verified_independent || 0)]
      ];
      rows.forEach(([name,val])=>{
        const line=document.createElement('div');line.className='wi-detail-line';
        text(line,name);text(line,val,'wi-detail-value');details.appendChild(line);
      });
    }
    controls.forEach((button,i)=>button.addEventListener('click',()=>show(i)));
    show(0);
  }
  const compare=document.getElementById('wi-relative-highlights');
  if(compare && source){
    const eligible=criteria.filter(x=>typeof x.mean_provisional === 'number' && x.n_provisional_used > 0);
    if(eligible.length<2){compare.textContent='برای مقایسه نسبی معیارها، دست‌کم دو معیار دارای امتیاز لازم است.';}
    else {
      const strongest=eligible.reduce((a,b)=>b.mean_provisional>a.mean_provisional?b:a);
      const weakest=eligible.reduce((a,b)=>b.mean_provisional<a.mean_provisional?b:a);
      if(strongest.mean_provisional===weakest.mean_provisional) compare.textContent='میانگین‌های موجود برابرند؛ تفاوت نسبی مشخصی دیده نمی‌شود.';
      else compare.textContent='بالاترین میانگین فعلی: '+strongest.label+' ('+fmt(strongest.mean_provisional)+' از ۱۰؛ '+fa(strongest.n_provisional_used)+' نظر). کمترین میانگین فعلی: '+weakest.label+' ('+fmt(weakest.mean_provisional)+' از ۱۰؛ '+fa(weakest.n_provisional_used)+' نظر). این مقایسه فقط داخل همین شرکت است و رتبه‌بندی محسوب نمی‌شود.';
    }
  }
  // Human-readable digits only; never rewrite script/json, attributes, links or inputs.
  const excluded=new Set(['SCRIPT','STYLE','CODE','PRE','TEXTAREA','OPTION','INPUT']);
  const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  let current;
  while((current=walker.nextNode())){
    let el=current.parentElement, skip=false;
    while(el){if(excluded.has(el.tagName)){skip=true;break;}el=el.parentElement;}
    if(!skip){
      const before=current.nodeValue;
      const after=before.replace(/[0-9\u0660-\u0669]/g,ch=>{
        const code=ch.charCodeAt(0);return numerals[code>=0x0660?code-0x0660:code-48];
      });
      if(before!==after)current.nodeValue=after;
    }
  }
})();
