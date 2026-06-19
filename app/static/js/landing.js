/* FireLens 랜딩 — Hero 위험지수 미니맵 (읽기전용) */

function riskColor(val) {
  if (val == null) return '#1a1a1a';
  if (val >= 80)   return '#8B0000';
  if (val >= 60)   return '#CC3300';
  if (val >= 40)   return '#FF6600';
  if (val >= 20)   return '#FFAA00';
  return '#2ECC71';
}

(async () => {
  const map = L.map('hero-map', {
    center: [37.5665, 126.978],
    zoom: 11,
    zoomControl: false,
    attributionControl: false,
    dragging: false,
    scrollWheelZoom: false,
    doubleClickZoom: false,
    boxZoom: false,
    keyboard: false,
    touchZoom: false,
  });

  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png', {
    subdomains: 'abcd',
    maxZoom: 19,
  }).addTo(map);

  try {
    const res  = await fetch('/api/geojson');
    const data = await res.json();

    const layer = L.geoJSON(data, {
      style: f => ({
        fillColor:   riskColor(f.properties.risk_index),
        fillOpacity: 0.78,
        color:       '#0A0A0A',
        weight:      0.3,
        opacity:     0.6,
      }),
      onEachFeature: (f, lyr) => {
        const p = f.properties;
        const name = (p.adm_nm || '').replace('서울특별시 ', '').split(' ').slice(1).join(' ');
        lyr.bindTooltip(
          `${name} · ${(p.risk_index || 0).toFixed(0)}`,
          { className: 'hero-tip', sticky: true }
        );
        lyr.on({
          mouseover: e => e.target.setStyle({ weight: 1.5, color: '#FF4500', fillOpacity: 0.95 }),
          mouseout:  e => layer.resetStyle(e.target),
          click:     () => { window.location.href = '/dashboard.html'; },
        });
      },
    }).addTo(map);

    map.fitBounds(layer.getBounds(), { padding: [10, 10] });
  } catch (e) {
    document.getElementById('hero-map').innerHTML =
      '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#888;font-family:monospace;font-size:12px">지도 로딩 실패 — 서버 확인</div>';
  }
})();
