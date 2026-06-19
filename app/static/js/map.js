/* FireMap — Leaflet.js 지도 + 패널 로직 */

const API = '';  // 같은 origin
let map, geojsonLayer, riskData = {};
let selectedAdmCd = null;
let currentHoverLayer = null;

const CLASS_COLOR = {
  '최우선 대응': '#e74c3c',
  '잠재 위험':   '#e67e22',
  '이력 관리':   '#3498db',
  '관찰 지역':   '#6c7a8d',
};

const BADGE_CLASS = {
  '최우선 대응': 'badge-최우선',
  '잠재 위험':   'badge-잠재',
  '이력 관리':   'badge-이력',
  '관찰 지역':   'badge-관찰',
};

const COMP_META = [
  { key: 'pct_fire_rate_per_10k', label: '화재율',    color: '#e74c3c', weight: 35 },
  { key: 'pct_ratio_65plus',      label: '65세+비율', color: '#e67e22', weight: 25 },
  { key: 'pct_cntr_dist_avg',     label: '119거리',   color: '#9b59b6', weight: 20 },
  { key: 'pct_old_bldg_ratio',    label: '노후건물',  color: '#f1c40f', weight: 12 },
  { key: 'pct_damage_per_fire',   label: '피해심각도',color: '#3498db', weight:  8 },
];

// ── 색상 함수 ────────────────────────────────────────────────
function riskColor(val) {
  if (val == null) return '#2e3148';
  if (val >= 80)   return '#c0392b';
  if (val >= 60)   return '#e74c3c';
  if (val >= 40)   return '#e67e22';
  if (val >= 20)   return '#f1c40f';
  return '#2ecc71';
}

// ── 지도 초기화 ──────────────────────────────────────────────
function initMap() {
  map = L.map('map', {
    center: [37.5665, 126.978],
    zoom: 11,
    zoomControl: true,
    doubleClickZoom: false,   // 지역 선택 시 의도치 않은 확대 방지
  });

  // 지도 영역 벗어날 때 툴팁 숨김
  map.on('mouseout', () => {
    tip.style.display = 'none';
    if (currentHoverLayer) {
      if (currentHoverLayer.feature?.properties?.adm_cd !== selectedAdmCd)
        geojsonLayer && geojsonLayer.resetStyle(currentHoverLayer);
      currentHoverLayer = null;
    }
  });

  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '© OpenStreetMap © CARTO',
    subdomains: 'abcd',
    maxZoom: 19,
  }).addTo(map);
}

// ── GeoJSON 로드 ─────────────────────────────────────────────
async function loadGeoJSON() {
  const res  = await fetch(`${API}/api/geojson`);
  const data = await res.json();

  // 통계 집계
  let counts = { '최우선 대응': 0, '잠재 위험': 0, '이력 관리': 0, '관찰 지역': 0 };
  data.features.forEach(f => {
    const p = f.properties;
    riskData[p.adm_cd] = p;
    if (counts[p.risk_class] !== undefined) counts[p.risk_class]++;
  });

  document.getElementById('cnt-urgent').textContent = counts['최우선 대응'];
  document.getElementById('cnt-latent').textContent = counts['잠재 위험'];
  document.getElementById('cnt-hist').textContent   = counts['이력 관리'];
  document.getElementById('cnt-watch').textContent  = counts['관찰 지역'];

  geojsonLayer = L.geoJSON(data, {
    style: feature => {
      const p = feature.properties;
      return {
        fillColor:   riskColor(p.risk_index),
        fillOpacity: 0.72,
        color:       '#ffffff',
        weight:      0.4,
        opacity:     0.5,
      };
    },
    onEachFeature: (feature, layer) => {
      const p = feature.properties;
      const name = (p.adm_nm || '').replace('서울특별시 ', '').split(' ').slice(1).join(' ');

      layer.on({
        mouseover: e => {
          if (currentHoverLayer && currentHoverLayer !== e.target) {
            if (currentHoverLayer.feature?.properties?.adm_cd !== selectedAdmCd)
              geojsonLayer.resetStyle(currentHoverLayer);
          }
          currentHoverLayer = e.target;
          e.target.setStyle({ weight: 2, color: '#fff', fillOpacity: 0.9 });
          e.target.bringToFront();
          tip.innerHTML = `
            <div class="popup-name">${name}</div>
            <div class="popup-idx">위험지수 ${(p.risk_index||0).toFixed(1)}</div>
            <div class="popup-cls">${p.risk_class || ''}</div>`;
          tip.style.display = 'block';
        },
        mousemove: e => {
          tip.style.left = e.originalEvent.clientX + 'px';
          tip.style.top  = e.originalEvent.clientY + 'px';
        },
        mouseout: e => {
          currentHoverLayer = null;
          if (e.target.feature?.properties?.adm_cd !== selectedAdmCd)
            geojsonLayer.resetStyle(e.target);
          tip.style.display = 'none';
        },
        click: () => selectDong(p.adm_cd),
      });
    },
  }).addTo(map);
}

// ── 행정동 선택 ──────────────────────────────────────────────
function selectDong(adm_cd) {
  selectedAdmCd = adm_cd;
  const p = riskData[adm_cd];
  if (!p) return;

  document.getElementById('panel-default').style.display = 'none';
  document.getElementById('panel-detail').style.display  = 'block';

  // 이름
  const name = (p.adm_nm || '').replace('서울특별시 ', '').split(' ').slice(1).join(' ');
  document.getElementById('d-name').textContent = name;

  // 배지
  const badge = document.getElementById('d-badge');
  badge.textContent  = p.risk_class || '';
  badge.className    = `risk-badge ${BADGE_CLASS[p.risk_class] || 'badge-관찰'}`;

  // 위험지수 바
  const idx = parseFloat(p.risk_index) || 0;
  document.getElementById('d-bar').style.width = idx + '%';
  document.getElementById('d-score').textContent = idx.toFixed(1);

  // 지표
  document.getElementById('d-fire').textContent    = (parseFloat(p.fire_rate_per_10k)||0).toFixed(1) + '건';
  document.getElementById('d-elderly').textContent = ((parseFloat(p.ratio_65plus)||0)*100).toFixed(1) + '%';
  document.getElementById('d-dist').textContent    = (parseFloat(p.cntr_dist_avg)||0).toFixed(2) + 'km';
  document.getElementById('d-old').textContent     = ((parseFloat(p.old_bldg_ratio)||0)*100).toFixed(1) + '%';

  // 구성요인 바
  const compEl = document.getElementById('d-components');
  compEl.innerHTML = '';
  COMP_META.forEach(m => {
    const pct = parseFloat(p[m.key]) || 0;
    compEl.innerHTML += `
      <div class="comp-row">
        <span class="comp-lbl">${m.label} (${m.weight}%)</span>
        <div class="comp-bar-wrap">
          <div class="comp-bar" style="width:${pct}%;background:${m.color}"></div>
        </div>
        <span class="comp-pct">${pct.toFixed(0)}</span>
      </div>`;
  });

  // AI 섹션 초기화
  document.getElementById('ai-loading').style.display = 'none';
  document.getElementById('ai-result').style.display  = 'none';
  document.getElementById('btn-analyze').disabled      = false;
  document.getElementById('btn-analyze').innerHTML     = '<span class="btn-icon">🛰️</span> AI 위성 분석 실행';

  // 분석 예정 안내
  const infoEl = document.getElementById('analyze-info');
  const riskIdx = parseFloat(p.risk_index) || 0;
  const hasHotspot = ['최우선 대응', '잠재 위험'].includes(p.risk_class);
  if (riskIdx >= 40) {
    const src = hasHotspot ? '화재 핫스팟 위성 이미지' : '행정동 중심 위성 이미지';
    infoEl.innerHTML = `<span class="analyze-info-ok">🛰️ ${src} 1장 분석 예정</span>`;
    infoEl.style.display = 'block';
  } else {
    infoEl.innerHTML = `<span class="analyze-info-warn">⚠️ 위험지수 40 미만 지역은 AI 분석 미지원</span>`;
    infoEl.style.display = 'block';
    document.getElementById('btn-analyze').disabled = true;
  }

  // 지도 하이라이트
  geojsonLayer.eachLayer(layer => {
    const lp = layer.feature?.properties;
    if (lp?.adm_cd === adm_cd) {
      layer.setStyle({ weight: 2.5, color: '#fff', fillOpacity: 0.95 });
    } else {
      geojsonLayer.resetStyle(layer);
    }
  });
}

// ── 모달 ─────────────────────────────────────────────────────
function runAnalysis() {
  if (!selectedAdmCd) return;
  const p = riskData[selectedAdmCd];
  const name = (p?.adm_nm || '').replace('서울특별시 ', '').split(' ').slice(1).join(' ');
  document.getElementById('modal-dong').textContent = name;
  document.getElementById('modal-overlay').style.display = 'flex';
}

function closeModal() {
  document.getElementById('modal-overlay').style.display = 'none';
}

async function confirmAnalysis() {
  closeModal();
  if (!selectedAdmCd) return;
  const btn = document.getElementById('btn-analyze');
  btn.disabled = true;
  btn.innerHTML = '분석 중...';
  document.getElementById('ai-loading').style.display = 'flex';
  document.getElementById('ai-result').style.display  = 'none';

  try {
    const res  = await fetch(`${API}/api/analyze/${selectedAdmCd}`, { method: 'POST' });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || '분석 실패');
    }
    const data = await res.json();

    // 위성 이미지
    document.getElementById('sat-img').src = `data:image/png;base64,${data.image_b64}`;

    // Vision 바
    const v = data.vision;
    setVBar('v-det',  'v-det-num',  v.building_deterioration);
    setVBar('v-den',  'v-den-num',  v.building_density);
    setVBar('v-risk', 'v-risk-num', v.fire_risk_score);

    // 골목 태그
    const alleyEl = document.getElementById('v-alley');
    const alleyMap = {
      wide:        '🟢 소방차 진입 가능',
      narrow:      '🟡 소방차 진입 어려움',
      very_narrow: '🔴 소방차 진입 불가',
    };
    alleyEl.textContent = alleyMap[v.alley_width] || v.alley_width;
    alleyEl.className   = `alley-tag alley-${v.alley_width}`;

    // LLM 리포트 (마크다운 렌더링)
    document.getElementById('ai-report').innerHTML = marked.parse(data.report);

    document.getElementById('ai-loading').style.display = 'none';
    document.getElementById('ai-result').style.display  = 'block';
    btn.innerHTML = data.cached ? '✅ 캐시된 분석 결과' : '✅ 분석 완료';

  } catch (e) {
    document.getElementById('ai-loading').style.display = 'none';
    btn.disabled = false;
    btn.innerHTML = '<span class="btn-icon">🛰️</span> AI 위성 분석 실행';
    alert('분석 실패: ' + e.message);
  }
}

function setVBar(barId, numId, val) {
  const pct = ((val || 0) / 10 * 100);
  document.getElementById(barId).style.width     = pct + '%';
  document.getElementById(numId).textContent     = val + '/10';
}

function showDefault() {
  document.getElementById('panel-default').style.display = 'block';
  document.getElementById('panel-detail').style.display  = 'none';
  selectedAdmCd = null;
  if (geojsonLayer) {
    geojsonLayer.eachLayer(l => geojsonLayer.resetStyle(l));
  }
}

// ── 부트스트랩 ───────────────────────────────────────────────
const tip = document.getElementById('map-tip');

// 포커스 잃으면 툴팁 강제 숨김
window.addEventListener('blur', () => { tip.style.display = 'none'; });
window.addEventListener('mouseleave', () => { tip.style.display = 'none'; });

(async () => {
  initMap();
  await loadGeoJSON();
})();
