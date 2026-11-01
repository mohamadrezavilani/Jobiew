/* Workplace Insights v0.38 — interactive admin coordinate picker.
 * No geocoding request until the reviewer explicitly clicks Search.
 * Does not modify approval fields or create/update company records.
 */
(function () {
  "use strict";
  function init() {
    const root = document.getElementById('wi-location-picker');
    if (!root) return;
    const latitude = document.getElementById('id_latitude');
    const longitude = document.getElementById('id_longitude');
    const status = document.getElementById('wi-location-picker-status');
    const query = document.getElementById('wi-location-search');
    const searchButton = document.getElementById('wi-location-search-button');
    const clearButton = document.getElementById('wi-location-clear-button');
    const results = document.getElementById('wi-location-search-results');
    if (!latitude || !longitude) {
      status.textContent = 'فیلدهای مختصات فرم یافت نشدند.';
      return;
    }
    if (!window.L) {
      status.textContent = 'نقشه بارگذاری نشد. اتصال اینترنت برای نقشه لازم است؛ فیلدهای مختصات همچنان قابل استفاده‌اند.';
      return;
    }
    const map = window.L.map('wi-location-map', {scrollWheelZoom: false}).setView([35.6892, 51.3890], 11);
    window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19, attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);
    let marker = null;
    let lastSearch = 0;
    function parseCoordinates() {
      const lat = Number(String(latitude.value).trim());
      const lng = Number(String(longitude.value).trim());
      if (!String(latitude.value).trim() || !String(longitude.value).trim()) return null;
      return Number.isFinite(lat) && Number.isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180
        ? window.L.latLng(lat, lng) : null;
    }
    function place(point, updateFields) {
      const p = window.L.latLng(point);
      if (!Number.isFinite(p.lat) || !Number.isFinite(p.lng) || Math.abs(p.lat) > 90 || Math.abs(p.lng) > 180) return;
      if (marker) marker.setLatLng(p);
      else {
        marker = window.L.marker(p, {draggable: true}).addTo(map);
        marker.on('dragend', function () { place(marker.getLatLng(), true); });
      }
      if (updateFields) {
        latitude.value = p.lat.toFixed(6);
        longitude.value = p.lng.toFixed(6);
        latitude.dispatchEvent(new Event('change', {bubbles: true}));
        longitude.dispatchEvent(new Event('change', {bubbles: true}));
      }
      status.textContent = 'مکان انتخاب شد: ' + p.lat.toFixed(6) + ' , ' + p.lng.toFixed(6) + ' — برای اصلاح، پین را بکشید یا دوباره روی نقشه کلیک کنید.';
    }
    const old = parseCoordinates();
    if (old) {
      place(old, false);
      map.setView(old, 15);
    } else {
      status.textContent = 'برای انتخاب مکان روی نقشه کلیک کنید. امکان بزرگ‌نمایی و جابه‌جایی نقشه وجود دارد.';
    }
    map.on('click', function (event) {place(event.latlng, true);});
    latitude.addEventListener('change', syncFromFields);
    longitude.addEventListener('change', syncFromFields);
    function syncFromFields() {
      const p = parseCoordinates();
      if (p) {place(p, false); map.panTo(p);}
      else if (!latitude.value.trim() && !longitude.value.trim()) removeSelection();
    }
    function removeSelection() {
      if (marker) {map.removeLayer(marker); marker = null;}
      status.textContent = 'انتخاب پاک شد؛ هیچ مختصاتی تعیین نشده است.';
    }
    clearButton.addEventListener('click', function () {
      latitude.value = '';
      longitude.value = '';
      results.replaceChildren();
      removeSelection();
      latitude.dispatchEvent(new Event('change', {bubbles: true}));
      longitude.dispatchEvent(new Event('change', {bubbles: true}));
    });
    searchButton.addEventListener('click', async function () {
      const q = query.value.trim();
      results.replaceChildren();
      if (q.length < 3 || q.length > 180) {status.textContent = 'برای جست‌وجو عبارت ۳ تا ۱۸۰ کاراکتری وارد کنید.';return;}
      const now = Date.now();
      if (now - lastSearch < 1500) {status.textContent = 'برای جست‌وجوی بعدی کمی صبر کنید.';return;}
      lastSearch = now;
      searchButton.disabled = true;
      status.textContent = 'در حال جست‌وجوی مکان…';
      try {
        const url = 'https://nominatim.openstreetmap.org/search?format=jsonv2&limit=5&countrycodes=ir&q=' + encodeURIComponent(q);
        const response = await fetch(url, {headers: {'Accept': 'application/json'}});
        if (!response.ok) throw new Error('search_http_error');
        const data = await response.json();
        if (!Array.isArray(data) || !data.length) {status.textContent = 'نتیجه‌ای پیدا نشد. می‌توانید مکان را مستقیم روی نقشه انتخاب کنید.';return;}
        data.slice(0, 5).forEach(function (item) {
          const lat = Number(item.lat), lng = Number(item.lon);
          if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
          const button = document.createElement('button');
          button.type = 'button';
          button.className = 'button';
          button.textContent = String(item.display_name || 'نتیجه جست‌وجو');
          button.addEventListener('click', function () {
            const p = window.L.latLng(lat, lng);
            map.setView(p, 16);
            place(p, true);
            results.replaceChildren();
          });
          results.appendChild(button);
        });
        status.textContent = 'یکی از نتایج را انتخاب کنید یا روی نقشه کلیک کنید.';
      } catch (e) {
        status.textContent = 'جست‌وجوی آنلاین در دسترس نیست؛ انتخاب مستقیم از روی نقشه همچنان ممکن است.';
      } finally { searchButton.disabled = false; }
    });
    query.addEventListener('keydown', function (e) {if (e.key === 'Enter') {e.preventDefault();searchButton.click();}});
    setTimeout(function () { map.invalidateSize(); }, 0);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
