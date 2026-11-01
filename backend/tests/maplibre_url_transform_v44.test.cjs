// Offline regression test: exercises actual v44 script's MapLibre constructor.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const path = require('path');
const scriptPath = path.resolve(__dirname, '../locations/static/locations/js/location_picker_v39.js');
const js = fs.readFileSync(scriptPath, 'utf8');
const elements = new Map();
const ids = ['wi-location-picker','id_latitude','id_longitude','wi-location-picker-status',
  'wi-location-search','wi-location-search-button','wi-location-clear-button','wi-location-search-results'];
for(const id of ids){
 elements.set(id, {value:'',textContent:'',after(){},addEventListener(){},replaceChildren(){}});
}
let captured;
class FakeMap {
 constructor(opts){captured=opts;}
 addControl(){}
 on(){}
 resize(){}
}
const origin = 'http://127.0.0.1:8000';
const ctx = {
 window:{location:{origin}, WebGLRenderingContext:function(){}, maplibregl:{Map:FakeMap,NavigationControl:class{}}},
 location:{origin,href:origin+'/admin/locations/companylocationreviewevent/add/'},
 document:{readyState:'complete', getElementById:id=>elements.get(id),createElement:()=>({addEventListener(){}})},
 maplibregl:{Map:FakeMap, NavigationControl:class{}},
 setTimeout(){},
 URL, Date,Number,Event:class{},console
};
vm.runInNewContext(js, ctx);
assert.ok(captured);
assert.equal(captured.style, origin+'/admin-map-assets/styles/liberty');
const f=captured.transformRequest;
const cases=[
 ['https://tiles.openfreemap.org/planet/20261011_080001_pt/10/658/403.pbf',origin+'/admin-map-assets/planet/20261011_080001_pt/10/658/403.pbf'],
 ['/admin-map-assets/planet/20261011_080001_pt/10/657/403.pbf',origin+'/admin-map-assets/planet/20261011_080001_pt/10/657/403.pbf'],
 ['https://tiles.openfreemap.org/sprites/ofm_f384/ofm',origin+'/admin-map-assets/sprites/ofm_f384/ofm'],
 ['https://tiles.openfreemap.org/fonts/Arial/0-255.pbf',origin+'/admin-map-assets/fonts/Arial/0-255.pbf'],
 [origin+'/admin-map-assets/planet/10/1/1.pbf',origin+'/admin-map-assets/planet/10/1/1.pbf'],
 ['https://elsewhere.example/test.pbf','https://elsewhere.example/test.pbf']
];
for(const [input,expected] of cases){
 const actual = f(input).url;
 assert.equal(actual,expected,`transformRequest(${input})`);
}
console.log('PASS: 6 browser URL cases (including original 403.pbf error)');
