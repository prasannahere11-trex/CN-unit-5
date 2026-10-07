# StationWiFi Lab 🚆📡
> **Railway Station WLAN Deployment & Performance Comparison Tool**  
> A high-fidelity, Python-based analytical & Monte-Carlo simulation platform for comparing enterprise wireless deployment architectures in crowded railway environments.

---

## 🌟 Key Highlights
- **Realistic Station Environment:** 200m &times; 60m concourse, 4 dedicated passenger platforms (150m &times; 10m each), ticket booking queues, food courts, executive lounges, concrete partitions, structural pillars, and dynamic crowd body attenuation.
- **Architectures Compared:**
  - **Configuration A (Traditional Macrocell):** 12 high-power APs (20 dBm, 100 mW), omni antennas, default 2.4 GHz preference, RSSI-only association, wide cells, high co-channel interference.
  - **Configuration B (Modern Microcell):** 36 low-power APs (12 dBm, 16 mW), sector antennas along tracks, 5 GHz-first band steering, active client load balancing (&le; 45 clients/AP), high spatial frequency reuse.
- **Full Physics & MAC Modeling:** Log-distance path loss with log-normal shadowing, obstacle line-of-sight intersection, SINR with co-channel & adjacent-channel interference, IEEE 802.11ac/ax MCS lookup tables, CSMA/CA airtime contention, M/M/1 queueing delay, frame retry latency, and Jain's fairness index.
- **Dynamic 60-Minute Timeline:** Models passenger influx curves and a **Train Arrival Burst** (3x passenger surge on platforms) to evaluate surge resilience.
- **Zero-Build Web Dashboard:** Flask backend + interactive HTML5 Canvas visualizer with live draggable APs, dynamic RSSI/SINR heatmaps, and Chart.js graphs.
- **Publication-Grade Reports:** Automatic HTML and PDF report generation with high-resolution Matplotlib figures, sensitivity curves, and an empirical field test validation guide.
- **NS-3 Scenario Exporter:** Bonus export to native NS-3 C++ simulation scripts.

---

## 📐 Mathematical & Physical Formulation (Viva Cheatsheet)

### 1. Log-Distance Path Loss with Shadowing & Obstacles
$$\text{PL}(d) = \text{PL}(d_0) + 10 \cdot n \cdot \log_{10}\left(\frac{d}{d_0}\right) + X_\sigma + \sum L_{\text{wall}} + \sum L_{\text{pillar}} + L_{\text{crowd}}$$
- $d_0 = 1.0\text{ m}$ (reference distance).
- $\text{PL}(d_0) = 20 \log_{10}(f_{\text{MHz}}) - 27.55$ (Free-space reference: $40.1\text{ dB}$ for $2.4\text{ GHz}$, $46.8\text{ dB}$ for $5\text{ GHz}$).
- $n = 3.0$ ($2.4\text{ GHz}$) / $3.3$ ($5\text{ GHz}$) in crowded indoor concourses.
- $X_\sigma \sim \mathcal{N}(0, \sigma^2)$ log-normal shadowing ($\sigma = 6.5\text{ dB}$).
- $L_{\text{wall}} = 8.0 - 10.0\text{ dB}$, $L_{\text{pillar}} = 6.0\text{ dB}$, $L_{\text{crowd}} = 3.0 - 5.0\text{ dB}$ body attenuation.

### 2. Received Signal Strength (RSSI) & SINR
$$\text{RSSI} = P_{\text{tx}} + G_{\text{tx}}(\theta) - \text{PL}(d)$$
$$\text{SINR} = 10 \log_{10} \left( \frac{10^{\text{RSSI} / 10}}{10^{N / 10} + \sum_{j \neq \text{serving}, \text{CCI}} 10^{\text{RSSI}_j / 10} + \alpha_{\text{adj}} \sum_{k, \text{ACI}} 10^{\text{RSSI}_k / 10}} \right)$$
- Thermal Noise Floor $N = -95\text{ dBm}$ ($20\text{ MHz}$) / $-92\text{ dBm}$ ($40\text{ MHz}$).
- Adjacent Channel Rejection $\text{ACR} = 25\text{ dB} \implies \alpha_{\text{adj}} = 10^{-2.5}$.

### 3. CSMA/CA MAC Contention & Airtime Throughput
- Demanded airtime per client $i$: $T_i = \frac{\text{Demand}_i}{\text{PHYRate}_i}$.
- Collision probability for $K$ contending stations:
  $$P_{\text{coll}} = 1 - (1 - \tau)^{K - 1}, \quad \text{where } \tau = \frac{2}{\text{CW}_{\text{min}} + 1}$$
- If total demanded airtime exceeds capacity $\eta_{\text{MAC}}$, fair-share airtime allocation applies:
  $$\text{Throughput}_i = \min\left( \text{Demand}_i, \frac{\text{PHYRate}_i \cdot \eta_{\text{MAC}} \cdot (1 - P_{\text{coll}})}{K} \right)$$
- Station aggregate is capped by the $2.0\text{ Gbps}$ fibre backhaul fair share.

### 4. Latency & Queueing Delay
$$\text{Latency} = L_0 + \left( \frac{\rho}{1 - \rho} \right) \cdot T_{\text{service}} + N_{\text{retry}} \cdot T_{\text{backoff}} + \text{Jitter}$$
- Modeled as an M/M/1 queue where $\rho = \text{AP Airtime Utilization} \in [0, 0.96]$.

### 5. Jain's Fairness Index
$$J(x) = \frac{\left( \sum_{i=1}^N x_i \right)^2}{N \cdot \sum_{i=1}^N x_i^2} \in [0.0, 1.0]$$

---

## 🚀 Quickstart Guide

### Prerequisites
- Python 3.10 or higher
- `pip` package manager

### 1. Installation
Clone or open the project folder:
```bash
cd stationwifi-lab
```

Install dependencies:
```bash
pip install -r requirements.txt
```

### 2. Run the Web Dashboard
```bash
python app.py
```
Open your browser and navigate to:
👉 **[http://localhost:5000](http://localhost:5000)**

### 3. Run Automated Unit Tests
```bash
pytest -v
```

---

## 💻 OS Setup Steps

### Windows (PowerShell)
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

### Linux (Ubuntu / Debian / Fedora)
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

### macOS
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

---

## 📁 Project Architecture
```text
stationwifi-lab/
├── app.py                  # Flask web server and REST API endpoints
├── config.yaml             # Complete station geometry, zones, and simulation defaults
├── requirements.txt        # Python dependency specifications
├── README.md               # Documentation and theoretical viva guide
├── sim/                    # Analytical & Monte-Carlo Simulation Engine
│   ├── __init__.py
│   ├── floorplan.py        # 2D geometry, obstacles, passenger distributions & train bursts
│   ├── placement.py        # AP placement (Engineered, K-Means) and Graph-Coloring channels
│   ├── propagation.py      # Log-distance path loss, log-normal shadowing, RSSI & SINR
│   ├── mac_model.py        # 802.11 MCS table, CSMA/CA airtime, association & throughput
│   ├── metrics.py          # Latency, loss, Jain's fairness index, and Monte-Carlo stats
│   └── runner.py           # Multi-trial Monte-Carlo, 60-min time-series & NS-3 exporter
├── report/                 # Technical Report Generation Engine
│   ├── generator.py        # High-res Matplotlib chart renderer & HTML/PDF compiler
│   └── template.html       # Jinja2 publication-grade report template
├── templates/
│   └── index.html          # Responsive single-page dashboard UI
├── static/
│   ├── css/style.css       # Clean dark/light theme design system
│   └── js/app.js           # HTML5 Canvas visualizer, draggable APs & Chart.js logic
└── tests/
    ├── test_propagation.py # RF path loss, frequency, obstacles and SINR tests
    └── test_mac_model.py   # MCS mapping, contention degradation & fairness tests
```

---

## 🎓 Viva Questions & Answers

1. **Why does Config A collapse during peak hours despite having higher transmit power (20 dBm)?**
   - *Answer:* High transmit power increases cell radius, causing wide RF overlap across APs. In $2.4\text{ GHz}$ (which only has 3 non-overlapping channels), APs constantly trigger Clear Channel Assessment (CCA) deferrals on each other. Furthermore, with 250+ clients contending on a single AP, CSMA/CA collision overhead degrades efficiency, causing airtime starvation and queue overflow.

2. **How does Config B solve the high-density problem?**
   - *Answer:* Config B uses microcells ($12\text{ dBm}$) with lower mounting and directional antennas on platforms. This shrinks cell collision domains, enables high spatial frequency reuse across 11 non-overlapping $5\text{ GHz}$ channels, and uses band steering with active load balancing (&le; 45 clients/AP) to prevent queue bloat.

3. **What is Jain's Fairness Index and why is it important in station Wi-Fi?**
   - *Answer:* Jain's Fairness Index measures whether all connected passengers receive an equitable share of bandwidth. In Config A, users near the AP monopolize airtime while far users suffer near-zero throughput ($J \approx 0.45$). In Config B, microcells and airtime fairness ensure consistent service quality station-wide ($J \approx 0.88$).

4. **How would you validate this simulation in a real railway station?**
   - *Answer:* Using `iperf3` for throughput measurements across client devices, ICMP `ping` for round-trip latency and packet loss distributions, and a spectrum analyzer / Wi-Fi Analyzer tool for physical RSSI and Co-Channel Interference mapping.
