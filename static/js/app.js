/**
 * StationWiFi Lab - Frontend Interactive Application Logic
 * Implements:
 * - HTML5 Canvas floorplan & dynamic RSSI heatmap rendering
 * - Interactive AP drag-and-drop placement
 * - Asynchronous Monte-Carlo simulation worker polling
 * - Chart.js comparative performance visualizations
 * - Comparison table & findings generation
 * - JSON scenario export/import and report generation
 */

// Application State
const state = {
    config: null,
    currentView: 'config_b', // 'config_a', 'config_b', 'side_by_side'
    heatmapMode: 'rssi',    // 'rssi', 'sinr', 'off'
    heatmapOpacity: 0.55,
    apsA: [],
    apsB: [],
    heatmapDataA: null,
    heatmapDataB: null,
    simulationResults: null,
    draggingAP: null,
    dragOffset: { x: 0, y: 0 },
    simulating: false,
    charts: {}
};

// Canvas coordinates mapping (World meters: X: 0..200, Y: -55..60)
const WORLD = {
    minX: -5,
    maxX: 205,
    minY: -58,
    maxY: 65,
    width: 210,
    height: 123
};

document.addEventListener('DOMContentLoaded', async () => {
    initTheme();
    initEventListeners();
    await loadInitialConfig();
    initCanvas();
    initCharts();
    await fetchHeatmap();
    await runSimulation(); // Run initial baseline simulation
});

// Theme Management
function initTheme() {
    const savedTheme = localStorage.getItem('stationwifi_theme') || 'dark';
    document.documentElement.setAttribute('data-theme', savedTheme);
    updateThemeIcon(savedTheme);

    document.getElementById('themeToggle').addEventListener('click', () => {
        const current = document.documentElement.getAttribute('data-theme');
        const next = current === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem('stationwifi_theme', next);
        updateThemeIcon(next);
        drawFloorplan();
        updateChartsTheme();
    });
}

function updateThemeIcon(theme) {
    document.getElementById('themeToggle').textContent = theme === 'dark' ? '🌙' : '☀️';
}

// Event Listeners
function initEventListeners() {
    // Slider Value Listeners
    const bindSlider = (id, valId, suffix = '') => {
        const slider = document.getElementById(id);
        const valElem = document.getElementById(valId);
        slider.addEventListener('input', () => {
            valElem.textContent = slider.value + suffix;
        });
    };

    bindSlider('rangeUsers', 'valUsers');
    bindSlider('rangeBackhaul', 'valBackhaul');
    bindSlider('rangeTxPowerA', 'valTxPowerA');
    bindSlider('rangeTxPowerB', 'valTxPowerB');
    bindSlider('rangeTrials', 'valTrials');

    // Scenario Dropdown
    document.getElementById('selectScenario').addEventListener('change', (e) => {
        const val = e.target.value;
        const badge = document.getElementById('badgeScenario');
        const slider = document.getElementById('rangeUsers');
        const valUsers = document.getElementById('valUsers');

        if (val === 'off_peak') {
            slider.value = 200;
            badge.textContent = 'Off-Peak';
        } else if (val === 'normal') {
            slider.value = 800;
            badge.textContent = 'Normal';
        } else if (val === 'peak') {
            slider.value = 2000;
            badge.textContent = 'Peak Rush';
        } else if (val === 'train_burst') {
            slider.value = 1500;
            badge.textContent = 'Train Burst';
        }
        valUsers.textContent = slider.value;
    });

    // Placement Dropdown
    document.getElementById('selectPlacement').addEventListener('change', async (e) => {
        if (e.target.value === 'kmeans') {
            // Reposition APs using synthetic K-means
            applyKMeansLayout();
        } else {
            await resetAPs();
        }
        await fetchHeatmap();
        drawFloorplan();
    });

    // View Tabs (Config A, Config B, Side-by-Side)
    document.querySelectorAll('.tab-btn[data-view]').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn[data-view]').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.currentView = btn.getAttribute('data-view');
            drawFloorplan();
        });
    });

    // Heatmap Controls
    document.getElementById('selectHeatmapMode').addEventListener('change', (e) => {
        state.heatmapMode = e.target.value;
        drawFloorplan();
    });

    document.getElementById('rangeHeatmapOpacity').addEventListener('input', (e) => {
        state.heatmapOpacity = parseFloat(e.target.value);
        drawFloorplan();
    });

    document.getElementById('btnResetAPs').addEventListener('click', async () => {
        await resetAPs();
        await fetchHeatmap();
        drawFloorplan();
    });

    // Simulation Trigger
    document.getElementById('btnRunSimulation').addEventListener('click', () => {
        runSimulation();
    });

    // JSON Save / Load
    document.getElementById('btnSaveScenario').addEventListener('click', saveScenarioJSON);
    document.getElementById('inputFileScenario').addEventListener('change', loadScenarioJSON);

    // NS-3 Export
    document.getElementById('btnExportNs3').addEventListener('click', () => {
        const configType = state.currentView === 'config_a' ? 'config_a' : 'config_b';
        window.location.href = `/api/export_ns3/${configType}`;
    });

    // Report Modal
    const modal = document.getElementById('modalReport');
    document.getElementById('btnOpenReportModal').addEventListener('click', () => {
        modal.style.display = 'flex';
    });
    document.getElementById('btnCloseReportModal').addEventListener('click', () => {
        modal.style.display = 'none';
    });
    modal.addEventListener('click', (e) => {
        if (e.target === modal) modal.style.display = 'none';
    });

    document.getElementById('btnDownloadHtmlReport').addEventListener('click', async () => {
        await generateReport('html');
    });
    document.getElementById('btnDownloadPdfReport').addEventListener('click', async () => {
        await generateReport('pdf');
    });
}

// Initial Configuration Loading
async function loadInitialConfig() {
    try {
        const res = await fetch('/api/config');
        state.config = await res.json();
        state.apsA = JSON.parse(JSON.stringify(state.config.default_aps_a));
        state.apsB = JSON.parse(JSON.stringify(state.config.default_aps_b));
    } catch (err) {
        console.error('Failed to load initial config:', err);
    }
}

async function resetAPs() {
    if (!state.config) return;
    state.apsA = JSON.parse(JSON.stringify(state.config.default_aps_a));
    state.apsB = JSON.parse(JSON.stringify(state.config.default_aps_b));
}

function applyKMeansLayout() {
    // Spatial density weighting
    const concourseAPsB = [
        { x: 20, y: 30 }, { x: 30, y: 15 }, { x: 35, y: 45 },
        { x: 50, y: 48 }, { x: 65, y: 48 }, { x: 55, y: 25 }, { x: 70, y: 15 },
        { x: 85, y: 30 }, { x: 95, y: 15 }, { x: 105, y: 35 },
        { x: 130, y: 45 }, { x: 155, y: 45 }, { x: 180, y: 45 },
        { x: 135, y: 15 }, { x: 160, y: 15 }, { x: 185, y: 15 }
    ];

    state.apsB.forEach((ap, idx) => {
        if (idx < concourseAPsB.length) {
            ap.x = concourseAPsB[idx].x;
            ap.y = concourseAPsB[idx].y;
        }
    });
}

// Heatmap Fetching
async function fetchHeatmap() {
    try {
        const [resA, resB] = await Promise.all([
            fetch('/api/heatmap/config_a', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ aps: state.apsA })
            }),
            fetch('/api/heatmap/config_b', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ aps: state.apsB })
            })
        ]);
        state.heatmapDataA = await resA.json();
        state.heatmapDataB = await resB.json();
    } catch (err) {
        console.error('Failed to fetch heatmap:', err);
    }
}

// Canvas Visualizer & Coordinate Transform
let canvas, ctx;

function initCanvas() {
    canvas = document.getElementById('floorplanCanvas');
    ctx = canvas.getContext('2d');

    function resizeCanvas() {
        const rect = canvas.parentElement.getBoundingClientRect();
        canvas.width = rect.width;
        canvas.height = rect.height;
        drawFloorplan();
    }

    window.addEventListener('resize', resizeCanvas);
    resizeCanvas();

    // Mouse Dragging for AP relocation
    canvas.addEventListener('mousedown', onCanvasMouseDown);
    canvas.addEventListener('mousemove', onCanvasMouseMove);
    window.addEventListener('mouseup', onCanvasMouseUp);
}

function worldToScreen(wx, wy) {
    const scaleX = canvas.width / WORLD.width;
    const scaleY = canvas.height / WORLD.height;
    const sx = (wx - WORLD.minX) * scaleX;
    // Invert Y so platforms are at bottom
    const sy = canvas.height - (wy - WORLD.minY) * scaleY;
    return { x: sx, y: sy };
}

function screenToWorld(sx, sy) {
    const scaleX = canvas.width / WORLD.width;
    const scaleY = canvas.height / WORLD.height;
    const wx = (sx / scaleX) + WORLD.minX;
    const wy = ((canvas.height - sy) / scaleY) + WORLD.minY;
    return { x: wx, y: wy };
}

function drawFloorplan() {
    if (!ctx || !state.config) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const isSideBySide = (state.currentView === 'side_by_side');
    const apsToDraw = (state.currentView === 'config_a') ? state.apsA : state.apsB;
    const heatmap = (state.currentView === 'config_a') ? state.heatmapDataA : state.heatmapDataB;

    // 1. Draw Heatmap (if enabled)
    if (state.heatmapMode !== 'off' && heatmap) {
        drawHeatmapGrid(heatmap);
    }

    // 2. Draw Zones
    const zones = state.config.zones || [];
    zones.forEach(z => {
        const p1 = worldToScreen(z.x, z.y + z.height);
        const p2 = worldToScreen(z.x + z.width, z.y);
        const w = p2.x - p1.x;
        const h = p2.y - p1.y;

        ctx.fillStyle = z.color + '22'; // 13% opacity tint
        ctx.fillRect(p1.x, p1.y, w, h);

        ctx.strokeStyle = z.color + '88';
        ctx.lineWidth = 1;
        ctx.strokeRect(p1.x, p1.y, w, h);

        // Zone Label
        ctx.fillStyle = '#ffffff';
        ctx.font = 'bold 10px sans-serif';
        ctx.fillText(z.name, p1.x + 8, p1.y + 14);
    });

    // 3. Draw Obstacles (Walls & Pillars)
    const obstacles = state.config.obstacles || [];
    obstacles.forEach(obs => {
        if (obs.type === 'wall') {
            const p1 = worldToScreen(obs.x1, obs.y1);
            const p2 = worldToScreen(obs.x2, obs.y2);
            ctx.strokeStyle = '#f43f5e';
            ctx.lineWidth = 3;
            ctx.beginPath();
            ctx.moveTo(p1.x, p1.y);
            ctx.lineTo(p2.x, p2.y);
            ctx.stroke();
        } else if (obs.type === 'pillar') {
            const pos = worldToScreen(obs.x, obs.y);
            ctx.fillStyle = '#cbd5e1';
            ctx.beginPath();
            ctx.arc(pos.x, pos.y, 4, 0, Math.PI * 2);
            ctx.fill();
        }
    });

    // 4. Draw APs
    if (isSideBySide) {
        // Draw both A and B
        state.apsA.forEach(ap => drawAPNode(ap, '#ef4444', 'A'));
        state.apsB.forEach(ap => drawAPNode(ap, '#10b981', 'B'));
    } else {
        apsToDraw.forEach(ap => {
            const color = (state.currentView === 'config_a') ? '#ef4444' : '#10b981';
            drawAPNode(ap, color);
        });
    }
}

function drawHeatmapGrid(heatmap) {
    const xCoords = heatmap.x_coords;
    const yCoords = heatmap.y_coords;
    const matrix = (state.heatmapMode === 'sinr') ? heatmap.sinr_matrix : heatmap.rssi_matrix;
    if (!matrix || !matrix.length) return;

    ctx.save();
    ctx.globalAlpha = state.heatmapOpacity;

    for (let r = 0; r < yCoords.length - 1; r++) {
        const y = yCoords[r];
        const nextY = yCoords[r + 1];
        for (let c = 0; c < xCoords.length - 1; c++) {
            const x = xCoords[c];
            const nextX = xCoords[c + 1];
            const val = matrix[r][c];

            // Color scale
            ctx.fillStyle = getHeatmapColor(val, state.heatmapMode);
            const p1 = worldToScreen(x, nextY);
            const p2 = worldToScreen(nextX, y);
            ctx.fillRect(p1.x, p1.y, Math.ceil(p2.x - p1.x), Math.ceil(p2.y - p1.y));
        }
    }
    ctx.restore();
}

function getHeatmapColor(val, mode) {
    if (mode === 'rssi') {
        // RSSI range: -90 (red) -> -75 (orange) -> -67 (yellow) -> -50 (green)
        if (val >= -60) return '#22c55e'; // Strong Green
        if (val >= -67) return '#84cc16'; // Light Green
        if (val >= -75) return '#eab308'; // Yellow
        if (val >= -82) return '#f97316'; // Orange
        return '#ef4444';                // Red
    } else {
        // SINR range: 0 dB (red) -> 12 dB (yellow) -> 25+ dB (green)
        if (val >= 24) return '#22c55e';
        if (val >= 18) return '#84cc16';
        if (val >= 12) return '#eab308';
        if (val >= 6) return '#f97316';
        return '#ef4444';
    }
}

function drawAPNode(ap, color, labelPrefix = '') {
    const pos = worldToScreen(ap.x, ap.y);

    // Glowing halo
    ctx.fillStyle = color + '33';
    ctx.beginPath();
    ctx.arc(pos.x, pos.y, 10, 0, Math.PI * 2);
    ctx.fill();

    // Center icon
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(pos.x, pos.y, 5, 0, Math.PI * 2);
    ctx.fill();

    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Text Label
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 9px sans-serif';
    const txt = labelPrefix ? `${labelPrefix}${ap.id}` : `AP${ap.id}`;
    ctx.fillText(txt, pos.x - 8, pos.y - 7);
}

// Drag and Drop APs
function onCanvasMouseDown(e) {
    const rect = canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    const wPos = screenToWorld(sx, sy);

    const activeAPs = (state.currentView === 'config_a') ? state.apsA : state.apsB;

    for (const ap of activeAPs) {
        const dist = Math.hypot(ap.x - wPos.x, ap.y - wPos.y);
        if (dist <= 6.0) { // 6 meter hit tolerance
            state.draggingAP = ap;
            state.dragOffset = { x: ap.x - wPos.x, y: ap.y - wPos.y };
            break;
        }
    }
}

function onCanvasMouseMove(e) {
    if (!state.draggingAP) return;
    const rect = canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    const wPos = screenToWorld(sx, sy);

    state.draggingAP.x = Math.max(0, Math.min(200, Math.round(wPos.x + state.dragOffset.x)));
    state.draggingAP.y = Math.max(-50, Math.min(60, Math.round(wPos.y + state.dragOffset.y)));

    drawFloorplan();
}

async function onCanvasMouseUp() {
    if (state.draggingAP) {
        state.draggingAP = null;
        await fetchHeatmap();
        drawFloorplan();
    }
}

// Chart.js Visualizations
function initCharts() {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const textColor = isDark ? '#94a3b8' : '#475569';
    const gridColor = isDark ? '#334155' : '#e2e8f0';

    Chart.defaults.color = textColor;
    Chart.defaults.borderColor = gridColor;

    // 1. Throughput Bar Chart
    state.charts.throughput = new Chart(document.getElementById('chartThroughput'), {
        type: 'bar',
        data: {
            labels: ['Average Throughput', 'Worst 5% (p5) Throughput', 'Aggregate Station Cap.'],
            datasets: [
                { label: 'Config A (12 APs)', data: [0.85, 0.22, 680], backgroundColor: '#f87171' },
                { label: 'Config B (36 APs)', data: [1.45, 1.25, 1160], backgroundColor: '#4ade80' }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { position: 'top' } },
            scales: { y: { beginAtZero: true, title: { display: true, text: 'Mbps' } } }
        }
    });

    // 2. 60-Minute Latency Timeline
    state.charts.timeline = new Chart(document.getElementById('chartTimeline'), {
        type: 'line',
        data: {
            labels: Array.from({ length: 60 }, (_, i) => `${i + 1}m`),
            datasets: [
                { label: 'Config A Latency (ms)', data: [], borderColor: '#f87171', backgroundColor: 'rgba(248, 113, 113, 0.1)', fill: true, tension: 0.3 },
                { label: 'Config B Latency (ms)', data: [], borderColor: '#4ade80', backgroundColor: 'rgba(74, 222, 128, 0.1)', fill: true, tension: 0.3 }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { position: 'top' } },
            scales: { y: { beginAtZero: true, title: { display: true, text: 'Round-Trip Latency (ms)' } } }
        }
    });

    // 3. RF Distribution
    state.charts.rfDist = new Chart(document.getElementById('chartRfDist'), {
        type: 'bar',
        data: {
            labels: ['< -80 dBm', '-80 to -75', '-75 to -67', '-67 to -60', '> -60 dBm'],
            datasets: [
                { label: 'Config A Signal Distribution', data: [8, 22, 35, 25, 10], backgroundColor: '#f87171' },
                { label: 'Config B Signal Distribution', data: [1, 5, 24, 45, 25], backgroundColor: '#4ade80' }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { position: 'top' } },
            scales: { y: { beginAtZero: true, title: { display: true, text: '% of Stations' } } }
        }
    });

    // 4. Radar Chart
    state.charts.radar = new Chart(document.getElementById('chartRadar'), {
        type: 'radar',
        data: {
            labels: ['Throughput (p5)', 'Low Latency', 'Packet Delivery', 'Fairness Index', 'Coverage (> -67dBm)', 'Cost Efficiency'],
            datasets: [
                { label: 'Config A', data: [20, 35, 60, 50, 65, 85], borderColor: '#f87171', backgroundColor: 'rgba(248, 113, 113, 0.2)' },
                { label: 'Config B', data: [90, 85, 95, 90, 95, 75], borderColor: '#4ade80', backgroundColor: 'rgba(74, 222, 128, 0.2)' }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: { r: { min: 0, max: 100 } }
        }
    });
}

function updateChartsTheme() {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const textColor = isDark ? '#94a3b8' : '#475569';
    const gridColor = isDark ? '#334155' : '#e2e8f0';

    Chart.defaults.color = textColor;
    Chart.defaults.borderColor = gridColor;

    Object.values(state.charts).forEach(c => {
        if (c) c.update();
    });
}

// Simulation Runner & Background Job Polling
async function runSimulation() {
    if (state.simulating) return;
    state.simulating = true;

    const banner = document.getElementById('progressBanner');
    const statusText = document.getElementById('progressStatusText');
    const percentText = document.getElementById('progressPercentText');
    const barFill = document.getElementById('progressBarFill');
    const runBtn = document.getElementById('btnRunSimulation');

    banner.style.display = 'block';
    runBtn.disabled = true;
    runBtn.textContent = '⏳ Simulating...';

    const payload = {
        scenario: document.getElementById('selectScenario').value,
        users: parseInt(document.getElementById('rangeUsers').value),
        trials: parseInt(document.getElementById('rangeTrials').value),
        seed: parseInt(document.getElementById('inputSeed').value),
        tx_power_a: parseFloat(document.getElementById('rangeTxPowerA').value),
        tx_power_b: parseFloat(document.getElementById('rangeTxPowerB').value),
        aps_a: state.apsA,
        aps_b: state.apsB
    };

    try {
        const startRes = await fetch('/api/simulate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const { job_id } = await startRes.json();

        // Poll progress
        let complete = false;
        while (!complete) {
            await new Promise(r => setTimeout(r, 400));
            const progRes = await fetch(`/api/progress/${job_id}`);
            const jobStatus = await progRes.json();

            statusText.textContent = jobStatus.message;
            percentText.textContent = `${jobStatus.progress}%`;
            barFill.style.width = `${jobStatus.progress}%`;

            if (jobStatus.status === 'COMPLETED') {
                complete = true;
                const resultsRes = await fetch(`/api/results/${job_id}`);
                const results = await resultsRes.json();
                state.simulationResults = results;
                updateDashboardResults(results);
            } else if (jobStatus.status === 'FAILED') {
                throw new Error(jobStatus.error || 'Simulation failed');
            }
        }
    } catch (err) {
        alert('Simulation error: ' + err.message);
    } finally {
        setTimeout(() => {
            banner.style.display = 'none';
        }, 1200);
        state.simulating = false;
        runBtn.disabled = false;
        runBtn.textContent = '🚀 Run Simulation';
    }
}

// Update UI with Simulation Results
function updateDashboardResults(results) {
    const a = results.config_a;
    const b = results.config_b;
    const findings = results.findings;

    // 1. Scorecard KPIs
    document.getElementById('kpiP5A').textContent = `${a.p5_throughput_mbps.mean} Mbps`;
    document.getElementById('kpiP5B').textContent = `${b.p5_throughput_mbps.mean} Mbps`;
    document.getElementById('badgeP5Winner').textContent = `Config B (+${findings.p5_gain_pct}%)`;

    document.getElementById('kpiLatA').textContent = `${a.mean_latency_ms.mean} ms`;
    document.getElementById('kpiLatB').textContent = `${b.mean_latency_ms.mean} ms`;
    document.getElementById('badgeLatWinner').textContent = `Config B (${findings.lat_reduction_pct}% lower)`;

    document.getElementById('kpiLossA').textContent = `${a.packet_loss_pct.mean}%`;
    document.getElementById('kpiLossB').textContent = `${b.packet_loss_pct.mean}%`;

    document.getElementById('kpiFairA').textContent = a.fairness_index.mean;
    document.getElementById('kpiFairB').textContent = b.fairness_index.mean;

    document.getElementById('kpiCostA').textContent = `$${a.total_capex_usd.toLocaleString()}`;
    document.getElementById('kpiCostB').textContent = `$${b.total_capex_usd.toLocaleString()}`;

    document.getElementById('kpiCostUserA').textContent = `$${a.cost_per_supported_user_usd.mean.toFixed(2)}`;
    document.getElementById('kpiCostUserB').textContent = `$${b.cost_per_supported_user_usd.mean.toFixed(2)}`;

    // 2. Findings Card
    const listElem = document.getElementById('listFindings');
    listElem.innerHTML = '';
    findings.key_findings.forEach(f => {
        const li = document.createElement('li');
        li.textContent = f;
        listElem.appendChild(li);
    });
    document.getElementById('boxRecommendation').textContent = findings.recommendation;

    // 3. Update Chart 1: Throughput Bar
    state.charts.throughput.data.datasets[0].data = [
        a.avg_throughput_mbps.mean,
        a.p5_throughput_mbps.mean,
        a.aggregate_throughput_mbps.mean
    ];
    state.charts.throughput.data.datasets[1].data = [
        b.avg_throughput_mbps.mean,
        b.p5_throughput_mbps.mean,
        b.aggregate_throughput_mbps.mean
    ];
    state.charts.throughput.update();

    // 4. Update Chart 2: Timeline
    if (results.time_series && results.time_series.timeline) {
        const tl = results.time_series.timeline;
        state.charts.timeline.data.datasets[0].data = tl.map(t => t.config_a.mean_latency_ms);
        state.charts.timeline.data.datasets[1].data = tl.map(t => t.config_b.mean_latency_ms);
        state.charts.timeline.update();
    }

    // 5. Update Chart 4: Radar
    const p5ScoreA = Math.min(100, a.p5_throughput_mbps.mean * 50);
    const p5ScoreB = Math.min(100, b.p5_throughput_mbps.mean * 50);
    const latScoreA = Math.max(10, 100 - a.mean_latency_ms.mean);
    const latScoreB = Math.max(10, 100 - b.mean_latency_ms.mean);
    const lossScoreA = Math.max(5, 100 - a.packet_loss_pct.mean * 8);
    const lossScoreB = Math.max(5, 100 - b.packet_loss_pct.mean * 8);

    state.charts.radar.data.datasets[0].data = [
        p5ScoreA, latScoreA, lossScoreA, a.fairness_index.mean * 100, a.pct_good_rssi.mean, 85
    ];
    state.charts.radar.data.datasets[1].data = [
        p5ScoreB, latScoreB, lossScoreB, b.fairness_index.mean * 100, b.pct_good_rssi.mean, 75
    ];
    state.charts.radar.update();

    // 6. Update Full Comparison Table
    updateComparisonTable(a, b);
}

function updateComparisonTable(a, b) {
    const tableBody = document.getElementById('tableBody');
    tableBody.innerHTML = '';

    const metrics = [
        { name: 'Average User Throughput', valA: `${a.avg_throughput_mbps.mean} Mbps`, valB: `${b.avg_throughput_mbps.mean} Mbps`, winner: 'Config B', unit: 'Mbps' },
        { name: 'Worst 5% User Throughput (p5)', valA: `${a.p5_throughput_mbps.mean} Mbps`, valB: `${b.p5_throughput_mbps.mean} Mbps`, winner: 'Config B', unit: 'Mbps' },
        { name: 'Station Aggregate Throughput', valA: `${a.aggregate_throughput_mbps.mean} Mbps`, valB: `${b.aggregate_throughput_mbps.mean} Mbps`, winner: 'Config B', unit: 'Mbps' },
        { name: 'Mean Round-Trip Latency', valA: `${a.mean_latency_ms.mean} ms`, valB: `${b.mean_latency_ms.mean} ms`, winner: 'Config B', unit: 'ms' },
        { name: '95th Percentile Latency', valA: `${a.p95_latency_ms.mean} ms`, valB: `${b.p95_latency_ms.mean} ms`, winner: 'Config B', unit: 'ms' },
        { name: 'Latency Jitter (StdDev)', valA: `${a.jitter_ms.mean} ms`, valB: `${b.jitter_ms.mean} ms`, winner: 'Config B', unit: 'ms' },
        { name: 'Signal Strength (Mean RSSI)', valA: `${a.mean_rssi_dbm.mean} dBm`, valB: `${b.mean_rssi_dbm.mean} dBm`, winner: 'Config B', unit: 'dBm' },
        { name: 'Good Signal Area (> -67 dBm)', valA: `${a.pct_good_rssi.mean}%`, valB: `${b.pct_good_rssi.mean}%`, winner: 'Config B', unit: '%' },
        { name: 'Mean SINR (Interference Margin)', valA: `${a.mean_sinr_db.mean} dB`, valB: `${b.mean_sinr_db.mean} dB`, winner: 'Config B', unit: 'dB' },
        { name: 'Packet Loss Rate', valA: `${a.packet_loss_pct.mean}%`, valB: `${b.packet_loss_pct.mean}%`, winner: 'Config B', unit: '%' },
        { name: 'Jain\'s Fairness Index', valA: `${a.fairness_index.mean}`, valB: `${b.fairness_index.mean}`, winner: 'Config B', unit: 'Score (0-1)' },
        { name: 'Initial CapEx Cost', valA: `$${a.total_capex_usd.toLocaleString()}`, valB: `$${b.total_capex_usd.toLocaleString()}`, winner: 'Config A', unit: 'USD' },
        { name: 'Cost / Supported User', valA: `$${a.cost_per_supported_user_usd.mean.toFixed(2)}`, valB: `$${b.cost_per_supported_user_usd.mean.toFixed(2)}`, winner: 'Config B', unit: 'USD/User' }
    ];

    metrics.forEach(m => {
        const tr = document.createElement('tr');
        const winnerBadge = m.winner === 'Config B'
            ? `<span class="kpi-winner winner-b">Config B Winner</span>`
            : `<span class="kpi-winner winner-a">Config A Winner</span>`;

        tr.innerHTML = `
            <td><strong>${m.name}</strong></td>
            <td>${m.valA}</td>
            <td>${m.valB}</td>
            <td>${winnerBadge}</td>
            <td>${m.unit}</td>
        `;
        tableBody.appendChild(tr);
    });
}

// JSON Scenario Save / Load
function saveScenarioJSON() {
    const data = {
        station: state.config.station,
        scenario: document.getElementById('selectScenario').value,
        users: parseInt(document.getElementById('rangeUsers').value),
        tx_power_a: parseFloat(document.getElementById('rangeTxPowerA').value),
        tx_power_b: parseFloat(document.getElementById('rangeTxPowerB').value),
        aps_a: state.apsA,
        aps_b: state.apsB
    };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `stationwifi_scenario_${data.scenario}.json`;
    a.click();
    URL.revokeObjectURL(url);
}

function loadScenarioJSON(e) {
    const file = e.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = async (evt) => {
        try {
            const data = JSON.parse(evt.target.result);
            if (data.aps_a) state.apsA = data.aps_a;
            if (data.aps_b) state.apsB = data.aps_b;
            if (data.users) {
                document.getElementById('rangeUsers').value = data.users;
                document.getElementById('valUsers').textContent = data.users;
            }
            await fetchHeatmap();
            drawFloorplan();
            alert('Scenario loaded successfully!');
        } catch (err) {
            alert('Failed to parse JSON scenario: ' + err.message);
        }
    };
    reader.readAsText(file);
}

// Generate Report
async function generateReport(format) {
    const msgElem = document.getElementById('reportStatusMessage');
    msgElem.textContent = `Compiling ${format.toUpperCase()} report with high-res figures...`;

    try {
        const res = await fetch('/api/report', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ format: format, results: state.simulationResults })
        });
        const data = await res.json();
        if (data.download_url) {
            msgElem.innerHTML = `✅ Report Ready: <a href="${data.download_url}" target="_blank" style="color: var(--brand-accent); font-weight: bold;">Open / Download ${data.filename}</a>`;
            window.open(data.download_url, '_blank');
        }
    } catch (err) {
        msgElem.textContent = 'Failed to generate report: ' + err.message;
    }
}
