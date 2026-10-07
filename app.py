"""
app.py - Flask Server and REST API for StationWiFi Lab.

Endpoints:
- GET  /                           -> Dashboard Single Page App
- GET  /api/config                 -> Current configuration and default scenario
- POST /api/simulate               -> Trigger background Monte-Carlo simulation
- GET  /api/progress/<job_id>      -> Job status and progress percentage
- GET  /api/results/<job_id>       -> Final simulation results and metrics
- GET  /api/heatmap/<config_type>  -> 2D spatial RSSI/SINR grid for floorplan canvas
- POST /api/report                 -> Auto-generate comparative HTML/PDF report
- GET  /api/download_report/<file> -> Download generated report file
- GET  /api/export.csv             -> Export CSV comparison table
- GET  /api/export_ns3/<config>    -> Export NS-3 simulation scenario file
"""

import os
import io
import csv
import yaml
from flask import Flask, render_template, request, jsonify, send_file, send_from_directory
from sim.floorplan import StationFloorplan
from sim.placement import APPlacementEngine, AccessPoint
from sim.propagation import PropagationModel
from sim.mac_model import MACModel
from sim.metrics import MetricsEngine
from sim.runner import SimulationRunner
from report.generator import ReportGenerator

# Initialize Flask app
app = Flask(__name__, static_folder="static", template_folder="templates")

# Load configuration
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

# Initialize engines
runner = SimulationRunner(CONFIG)
report_gen = ReportGenerator(CONFIG)

# Store last completed simulation results in memory for CSV export
last_simulation_results = None


@app.route("/")
def index():
    """Renders the main single-page dashboard."""
    return render_template("index.html")


@app.route("/api/config", methods=["GET"])
def get_config():
    """Returns default station geometry, zones, parameters and AP presets."""
    floorplan = StationFloorplan(CONFIG)
    default_aps_a = APPlacementEngine.get_default_config_a(CONFIG)
    default_aps_b = APPlacementEngine.get_default_config_b(CONFIG)

    return jsonify({
        "station": CONFIG.get("station", {}),
        "zones": CONFIG.get("zones", []),
        "obstacles": CONFIG.get("obstacles", []),
        "passengers": CONFIG.get("passengers", {}),
        "propagation": CONFIG.get("propagation", {}),
        "configurations": CONFIG.get("configurations", {}),
        "default_aps_a": [
            {
                "id": ap.id, "name": ap.name, "x": ap.x, "y": ap.y, "height_m": ap.height_m,
                "tx_power_dbm": ap.tx_power_dbm, "antenna_gain_dbi": ap.antenna_gain_dbi,
                "antenna_type": ap.antenna_type, "antenna_azimuth_deg": ap.antenna_azimuth_deg,
                "antenna_beamwidth_deg": ap.antenna_beamwidth_deg,
                "channel_24": ap.channel_24, "channel_5": ap.channel_5,
                "channel_width_24_mhz": ap.channel_width_24_mhz, "channel_width_5_mhz": ap.channel_width_5_mhz,
                "band_preference": ap.band_preference, "band_steering": ap.band_steering,
                "load_balancing": ap.load_balancing, "max_clients": ap.max_clients,
                "cost_hardware_usd": ap.cost_hardware_usd, "cost_cabling_usd": ap.cost_cabling_usd
            }
            for ap in default_aps_a
        ],
        "default_aps_b": [
            {
                "id": ap.id, "name": ap.name, "x": ap.x, "y": ap.y, "height_m": ap.height_m,
                "tx_power_dbm": ap.tx_power_dbm, "antenna_gain_dbi": ap.antenna_gain_dbi,
                "antenna_type": ap.antenna_type, "antenna_azimuth_deg": ap.antenna_azimuth_deg,
                "antenna_beamwidth_deg": ap.antenna_beamwidth_deg,
                "channel_24": ap.channel_24, "channel_5": ap.channel_5,
                "channel_width_24_mhz": ap.channel_width_24_mhz, "channel_width_5_mhz": ap.channel_width_5_mhz,
                "band_preference": ap.band_preference, "band_steering": ap.band_steering,
                "load_balancing": ap.load_balancing, "max_clients": ap.max_clients,
                "cost_hardware_usd": ap.cost_hardware_usd, "cost_cabling_usd": ap.cost_cabling_usd
            }
            for ap in default_aps_b
        ]
    })


@app.route("/api/simulate", methods=["POST"])
def simulate():
    """Starts an asynchronous Monte-Carlo simulation job."""
    params = request.get_json() or {}
    job_id = runner.start_simulation_job(params)
    return jsonify({"job_id": job_id, "status": "QUEUED", "message": "Simulation started in background."})


@app.route("/api/progress/<job_id>", methods=["GET"])
def get_progress(job_id):
    """Returns the current execution progress and status of a simulation job."""
    status_data = runner.get_job_status(job_id)
    if not status_data:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(status_data)


@app.route("/api/results/<job_id>", methods=["GET"])
def get_results(job_id):
    """Returns completed simulation results for a job."""
    global last_simulation_results
    results = runner.get_job_results(job_id)
    if not results:
        return jsonify({"error": "Results not ready or job failed"}), 404
    last_simulation_results = results
    return jsonify(results)


@app.route("/api/heatmap/<config_type>", methods=["POST", "GET"])
def get_heatmap(config_type):
    """Computes a 2D spatial matrix of RSSI and SINR values across the station floorplan."""
    floorplan = StationFloorplan(CONFIG)
    prop = PropagationModel(CONFIG, floorplan)

    # Optional custom APs in request body
    custom_aps_data = None
    if request.is_json:
        body = request.get_json()
        custom_aps_data = body.get("aps")

    if custom_aps_data:
        aps = [AccessPoint(**item) for item in custom_aps_data]
    else:
        is_config_b = (config_type.lower() == "config_b")
        aps = APPlacementEngine.get_default_config_b(CONFIG) if is_config_b else APPlacementEngine.get_default_config_a(CONFIG)

    grid = prop.generate_heatmap_grid(aps, grid_step=3.0)
    return jsonify(grid)


@app.route("/api/report", methods=["POST"])
def generate_report():
    """Builds HTML and PDF comparative evaluation reports."""
    global last_simulation_results
    body = request.get_json() or {}
    report_format = body.get("format", "html").lower()

    sim_results = body.get("results") or last_simulation_results
    if not sim_results:
        # Run a quick default simulation if none exists
        res_a = runner.run_monte_carlo("config_a", num_trials=10)
        res_b = runner.run_monte_carlo("config_b", num_trials=10)
        default_aps_a = APPlacementEngine.get_default_config_a(CONFIG)
        default_aps_b = APPlacementEngine.get_default_config_b(CONFIG)
        ts = runner.run_time_series(default_aps_a, default_aps_b, duration_min=60)
        findings = runner.generate_findings_and_recommendations(res_a, res_b, "Normal")
        sim_results = {
            "scenario_key": "normal",
            "config_a": res_a,
            "config_b": res_b,
            "time_series": ts,
            "findings": findings
        }
        last_simulation_results = sim_results

    if report_format == "pdf":
        file_path = report_gen.generate_pdf_report(sim_results, "stationwifi_report.pdf")
        filename = "stationwifi_report.pdf"
    else:
        file_path = report_gen.generate_html_report(sim_results, "stationwifi_report.html")
        filename = "stationwifi_report.html"

    return jsonify({
        "status": "SUCCESS",
        "filename": filename,
        "download_url": f"/api/download_report/{filename}"
    })


@app.route("/api/download_report/<filename>", methods=["GET"])
def download_report(filename):
    """Serves the generated report file."""
    reports_dir = os.path.join(os.path.dirname(__file__), "reports_generated")
    return send_from_directory(reports_dir, filename, as_attachment=False)


@app.route("/api/export.csv", methods=["GET"])
def export_csv():
    """Exports comparison metrics as a downloadable CSV."""
    global last_simulation_results
    if not last_simulation_results:
        # Provide baseline data if simulation hasn't run yet
        res_a = runner.run_monte_carlo("config_a", num_trials=5)
        res_b = runner.run_monte_carlo("config_b", num_trials=5)
        last_simulation_results = {"config_a": res_a, "config_b": res_b}

    res_a = last_simulation_results.get("config_a", {})
    res_b = last_simulation_results.get("config_b", {})

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["StationWiFi Lab - Comparative Performance Data"])
    writer.writerow(["Metric", "Config A (Traditional 12 APs)", "Config B (Microcell 36 APs)", "Unit"])

    metrics_list = [
        ("Average User Throughput", "avg_throughput_mbps", "Mbps"),
        ("Worst 5% User Throughput (p5)", "p5_throughput_mbps", "Mbps"),
        ("Station Aggregate Throughput", "aggregate_throughput_mbps", "Mbps"),
        ("Mean Round-Trip Latency", "mean_latency_ms", "ms"),
        ("95th Percentile Latency", "p95_latency_ms", "ms"),
        ("Latency Jitter (StdDev)", "jitter_ms", "ms"),
        ("Mean RSSI", "mean_rssi_dbm", "dBm"),
        ("Area with Good Signal (> -67 dBm)", "pct_good_rssi", "%"),
        ("Area with Poor Signal (< -75 dBm)", "pct_poor_rssi", "%"),
        ("Mean SINR", "mean_sinr_db", "dB"),
        ("Worst 5% SINR", "p5_sinr_db", "dB"),
        ("Packet Loss Rate", "packet_loss_pct", "%"),
        ("Jain's Fairness Index", "fairness_index", "Score (0-1)"),
        ("Coverage Reliability", "coverage_pct", "%"),
        ("Total Initial CapEx", "total_capex_usd", "USD"),
        ("Cost per Supported User", "cost_per_supported_user_usd", "USD/User"),
    ]

    for label, key, unit in metrics_list:
        val_a = res_a.get(key, {}).get("mean", res_a.get(key, "N/A")) if isinstance(res_a.get(key), dict) else res_a.get(key, "N/A")
        val_b = res_b.get(key, {}).get("mean", res_b.get(key, "N/A")) if isinstance(res_b.get(key), dict) else res_b.get(key, "N/A")
        writer.writerow([label, val_a, val_b, unit])

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name="stationwifi_comparison.csv"
    )


@app.route("/api/export_ns3/<config_type>", methods=["GET"])
def export_ns3(config_type):
    """Exports NS-3 simulation scenario file."""
    is_config_b = (config_type.lower() == "config_b")
    aps = APPlacementEngine.get_default_config_b(CONFIG) if is_config_b else APPlacementEngine.get_default_config_a(CONFIG)
    width = float(CONFIG.get("station", {}).get("width", 200.0))
    height = float(CONFIG.get("station", {}).get("height", 60.0))

    ns3_code = SimulationRunner.export_ns3_scenario(config_type, aps, width, height)
    return send_file(
        io.BytesIO(ns3_code.encode("utf-8")),
        mimetype="text/plain",
        as_attachment=True,
        download_name=f"stationwifi_{config_type}.cc"
    )


if __name__ == "__main__":
    print("=" * 70)
    print(" StationWiFi Lab - Railway Station WLAN Simulation & Comparison Tool")
    print(" Dashboard starting at http://127.0.0.1:5000")
    print("=" * 70)
    app.run(host="0.0.0.0", port=5000, debug=True)
