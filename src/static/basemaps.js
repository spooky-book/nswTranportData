// Shared keyless basemaps for the map pages. Usage: addBasemaps(map);
// Esri and NSW Spatial Services URLs are {y}/{x}, not {x}/{y}.
function addBasemaps(map, defaultName = 'Light Gray') {
    const osmAttribution = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
    const baseLayers = {
        'Light Gray': L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
            attribution: 'Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors',
            maxNativeZoom: 16,
            maxZoom: 20
        }),
        'OpenStreetMap': L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: osmAttribution,
            maxNativeZoom: 19,
            maxZoom: 20
        }),
        'CyclOSM (paths & cycleways)': L.tileLayer('https://{s}.tile-cyclosm.openstreetmap.fr/cyclosm/{z}/{x}/{y}.png', {
            attribution: '<a href="https://www.cyclosm.org">CyclOSM</a> | ' + osmAttribution,
            subdomains: 'abc',
            maxNativeZoom: 18,
            maxZoom: 20
        }),
        'NSW Imagery': L.tileLayer('https://maps.six.nsw.gov.au/arcgis/rest/services/public/NSW_Imagery/MapServer/tile/{z}/{y}/{x}', {
            attribution: '&copy; Spatial Services NSW',
            maxNativeZoom: 20,
            maxZoom: 20
        })
    };
    baseLayers[defaultName].addTo(map);
    L.control.layers(baseLayers, null, { position: 'bottomright' }).addTo(map);
    return baseLayers;
}
