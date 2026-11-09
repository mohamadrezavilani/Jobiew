/* Jobiew v2.0.19 — private homepage prototype, public-safe metadata only.
   No synthetic company data, no internal scores, no client-side publication path.
*/
(function () {
  'use strict';
  const body = document.body;
  const drawer = document.getElementById('drawer');
  const open = document.getElementById('open');
  const close = document.getElementById('close');
  const scrim = document.getElementById('scrim');
  let previousFocus = null;
  function showDrawer() {
    previousFocus = document.activeElement;
    scrim.hidden = false;
    scrim.classList.add('show');
    drawer.inert = false;
    drawer.classList.add('show');
    open.setAttribute('aria-expanded', 'true');
    close.focus();
    document.body.style.overflow = 'hidden';
  }
  function hideDrawer() {
    drawer.inert = true;
    drawer.classList.remove('show');
    scrim.classList.remove('show');
    scrim.hidden = true;
    open.setAttribute('aria-expanded', 'false');
    document.body.style.overflow = '';
    if (previousFocus && previousFocus.isConnected) previousFocus.focus();
    else open.focus();
  }
  open.addEventListener('click', showDrawer);
  close.addEventListener('click', hideDrawer);
  scrim.addEventListener('click', hideDrawer);
  document.addEventListener('keydown', (event) => {
    if (drawer.inert) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      hideDrawer();
      return;
    }
    if (event.key !== 'Tab') return;
    const focusable = Array.from(drawer.querySelectorAll(
      'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled)'
    )).filter(el => el.offsetParent !== null);
    if (!focusable.length) { event.preventDefault(); close.focus(); return; }
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first.focus();
    }
  });

  const mapContainer = document.getElementById('home-map');
  const mapEmpty = document.getElementById('map-empty');
  const title = document.getElementById('map-status-title');
  const detail = document.getElementById('map-status-text');
  const companyRows = new Map(Array.from(document.querySelectorAll('.company[data-company-id]'))
    .map(el => [el.dataset.companyId, el]));
  function status(heading, description) {
    title.textContent = heading;
    detail.textContent = description;
    mapEmpty.hidden = false;
    mapContainer.hidden = true;
  }
  function validFeature(feature) {
    const coords = feature && feature.geometry && feature.geometry.coordinates;
    const properties = feature && feature.properties;
    return Array.isArray(coords) && coords.length === 2 &&
      coords.every(Number.isFinite) && Math.abs(coords[0]) <= 180 &&
      Math.abs(coords[1]) <= 90 && properties &&
      typeof properties.company_id === 'string' &&
      companyRows.has(properties.company_id);
  }

  (async function displayVerifiedLocations() {
    let features;
    try {
      const result = await fetch(body.dataset.geojsonUrl, {
        method: 'GET', credentials: 'same-origin', headers: {Accept: 'application/geo+json, application/json'}
      });
      if (!result.ok) throw new Error('verified location API unavailable');
      const data = await result.json();
      features = data && Array.isArray(data.features) ? data.features.filter(validFeature) : [];
    } catch (_error) {
      status('موقعیت‌ها بارگیری نشدند', 'امکان دریافت دادهٔ تأییدشده فراهم نیست. فهرست شرکت‌ها همچنان در دسترس است.');
      return;
    }
    if (!features.length) {
      status('موقعیت تأییدشده‌ای در این صفحه وجود ندارد',
        'نبود موقعیت روی نقشه به معنی نبود شرکت یا فعالیت آن در تهران نیست.');
      return;
    }
    if (!window.maplibregl || typeof maplibregl.Map !== 'function' ||
        (typeof maplibregl.supported === 'function' && !maplibregl.supported())) {
      status('مرورگر از این نقشه پشتیبانی نمی‌کند', 'برای دیدن اطلاعات، از لینک شرکت‌ها استفاده کنید.');
      return;
    }
    mapContainer.hidden = false;
    try {
      if (typeof maplibregl.setRTLTextPlugin === 'function') {
        try {
          await maplibregl.setRTLTextPlugin(
            'https://unpkg.com/@mapbox/mapbox-gl-rtl-text@0.3.0/dist/mapbox-gl-rtl-text.js', false
          );
        } catch (_ignore) { /* Map remains usable if RTL support is unavailable. */ }
      }
      const map = new maplibregl.Map({
        container: mapContainer, style: 'https://tiles.openfreemap.org/styles/liberty',
        center: [51.389, 35.6892], zoom: 10, minZoom: 3, maxZoom: 18,
        attributionControl: true, cooperativeGestures: true
      });
      map.addControl(new maplibregl.NavigationControl({showCompass: false}), 'top-left');
      const bounds = new maplibregl.LngLatBounds();
      for (const feature of features) {
        const company = companyRows.get(feature.properties.company_id);
        const link = document.createElement('a');
        link.href = company.href;
        link.textContent = company.querySelector('.cname').textContent;
        link.rel = 'nofollow';
        const wrapper = document.createElement('div');
        wrapper.dir = 'rtl';
        wrapper.appendChild(link);
        const point = feature.geometry.coordinates;
        bounds.extend(point);
        new maplibregl.Marker({color: '#21a6a0'})
          .setLngLat(point)
          .setPopup(new maplibregl.Popup({offset: 20}).setDOMContent(wrapper))
          .addTo(map);
      }
      map.on('load', () => { mapEmpty.hidden = true; map.resize(); });
      map.on('error', () => {
        mapEmpty.hidden = false;
        title.textContent = 'بارگذاری نقشه با مشکل مواجه شد';
        detail.textContent = 'مکان‌های تأییدشده را می‌توان در صفحهٔ مستقل نقشه مشاهده کرد.';
      });
      if (features.length === 1) { map.setCenter(features[0].geometry.coordinates); map.setZoom(12); }
      else map.fitBounds(bounds, {padding: 50, maxZoom: 13, duration: 0});
    } catch (_error) {
      status('نقشه در این مرورگر باز نشد', 'فهرست شرکت‌ها و صفحهٔ نقشهٔ مستقل همچنان در دسترس هستند.');
    }
  })();
})();