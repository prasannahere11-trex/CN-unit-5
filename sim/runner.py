"""
sim/runner.py - Monte-Carlo Simulator, 60-Minute Time Series Engine, and NS-3 Exporter.

Features:
1. Multi-trial Monte-Carlo simulation with statistical confidence intervals.
2. 60-Minute dynamic time-series simulation modeling passenger influx & train arrival bursts.
3. Rule-based automated findings & engineering recommendations generator.
4. Background job management with progress updates.
5. NS-3 simulation scenario file generator (C++ / Python format).
"""

import copy
import time
import math
import uuid
import threading
import numpy as np
from typing import List, Dict, Tuple, Optional, Any, Callable
from .floorplan import StationFloorplan, User
from .placement import APPlacementEngine, AccessPoint
from .propagation import PropagationModel
from .mac_model import MACModel
from .metrics import MetricsEngine


class SimulationRunner:
    """Orchestrates WLAN simulations, time-series generation, and background jobs."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.Lock()

    def run_monte_carlo(self, config_type: str,
                        custom_aps: Optional[List[AccessPoint]] = None,
                        scenario_key: str = "normal",
                        num_users: Optional[int] = None,
                        num_trials: int = 30,
                        seed: int = 42,
                        progress_callback: Optional[Callable[[float, str], None]] = None) -> Dict[str, Any]:
        """
        Executes N Monte-Carlo trials for a given deployment configuration.
        """
        floorplan = StationFloorplan(self.config)
        propagation = PropagationModel(self.config, floorplan)
        mac_model = MACModel(self.config, propagation)

        is_config_b = (config_type.lower() == "config_b")
        if custom_aps is not None and len(custom_aps) > 0:
            aps = copy.deepcopy(custom_aps)
        else:
            aps = APPlacementEngine.get_default_config_b(self.config) if is_config_b else APPlacementEngine.get_default_config_a(self.config)

        trials = []
        rng = np.random.default_rng(seed)

        for trial_idx in range(num_trials):
            trial_seed = int(rng.integers(0, 1000000))
            trial_rng = np.random.default_rng(trial_seed)

            # Generate users for this trial
            users = floorplan.generate_passengers(
                scenario_key=scenario_key,
                custom_user_count=num_users,
                seed=trial_seed
            )

            # Associate and simulate MAC airtime
            mac_model.associate_clients(users, aps, is_config_b=is_config_b, rng=trial_rng)
            mac_model.simulate_mac_throughput(users, aps, is_config_b=is_config_b, rng=trial_rng)

            # Compute metrics
            single_metrics = MetricsEngine.compute_single_run_metrics(users, aps, propagation, floorplan)
            trials.append(single_metrics)

            if progress_callback is not None and num_trials > 0:
                pct = ((trial_idx + 1) / num_trials) * 100.0
                progress_callback(pct, f"Completed trial {trial_idx + 1}/{num_trials}")

        aggregated = MetricsEngine.aggregate_monte_carlo_results(trials)
        aggregated["config_type"] = config_type
        aggregated["scenario_key"] = scenario_key
        aggregated["ap_count"] = len(aps)
        return aggregated

    def run_time_series(self, aps_a: List[AccessPoint], aps_b: List[AccessPoint],
                        duration_min: int = 60, seed: int = 42) -> Dict[str, Any]:
        """
        Simulates a 60-minute time timeline with dynamic passenger arrivals and a train burst event.
        - Minutes 0-15: Normal traffic (~800 users).
        - Minutes 15-30: Train Arrival Burst on Platforms 3 & 4 (users surge to ~1800).
        - Minutes 30-45: Crowd dispersal into Concourse & Food Court (~1400 users).
        - Minutes 45-60: Return to steady state (~900 users).
        """
        floorplan = StationFloorplan(self.config)
        propagation = PropagationModel(self.config, floorplan)
        mac_model = MACModel(self.config, propagation)

        rng = np.random.default_rng(seed)
        timeline = []

        for minute in range(1, duration_min + 1):
            # Dynamic passenger count model
            if minute < 15:
                # Steady state
                user_count = int(750 + 80 * math.sin(minute / 3.0) + rng.integers(-30, 30))
                scenario = "normal"
            elif 15 <= minute <= 30:
                # Train burst peak
                progress = (minute - 15) / 15.0
                user_count = int(800 + 1100 * math.sin(progress * math.pi) + rng.integers(-40, 40))
                scenario = "train_burst"
            elif 30 < minute <= 45:
                # Dispersal
                decay = (45 - minute) / 15.0
                user_count = int(900 + 600 * decay + rng.integers(-30, 30))
                scenario = "normal"
            else:
                user_count = int(850 + 60 * math.cos(minute / 4.0) + rng.integers(-25, 25))
                scenario = "normal"

            step_seed = int(rng.integers(0, 1000000))
            step_rng = np.random.default_rng(step_seed)

            # Generate users for this minute
            users = floorplan.generate_passengers(scenario_key=scenario, custom_user_count=user_count, seed=step_seed)

            # 1. Run Config A
            users_a = copy.deepcopy(users)
            aps_a_copy = copy.deepcopy(aps_a)
            mac_model.associate_clients(users_a, aps_a_copy, is_config_b=False, rng=step_rng)
            mac_model.simulate_mac_throughput(users_a, aps_a_copy, is_config_b=False, rng=step_rng)
            kpi_a = MetricsEngine.compute_single_run_metrics(users_a, aps_a_copy, propagation, floorplan)

            # 2. Run Config B
            users_b = copy.deepcopy(users)
            aps_b_copy = copy.deepcopy(aps_b)
            mac_model.associate_clients(users_b, aps_b_copy, is_config_b=True, rng=step_rng)
            mac_model.simulate_mac_throughput(users_b, aps_b_copy, is_config_b=True, rng=step_rng)
            kpi_b = MetricsEngine.compute_single_run_metrics(users_b, aps_b_copy, propagation, floorplan)

            timeline.append({
                "minute": minute,
                "user_count": user_count,
                "is_burst": (15 <= minute <= 30),
                "config_a": {
                    "avg_throughput_mbps": kpi_a["avg_throughput_mbps"],
                    "p5_throughput_mbps": kpi_a["p5_throughput_mbps"],
                    "aggregate_throughput_mbps": kpi_a["aggregate_throughput_mbps"],
                    "mean_latency_ms": kpi_a["mean_latency_ms"],
                    "p95_latency_ms": kpi_a["p95_latency_ms"],
                    "packet_loss_pct": kpi_a["packet_loss_pct"],
                    "fairness_index": kpi_a["fairness_index"],
                    "max_ap_load": kpi_a["max_ap_load"]
                },
                "config_b": {
                    "avg_throughput_mbps": kpi_b["avg_throughput_mbps"],
                    "p5_throughput_mbps": kpi_b["p5_throughput_mbps"],
                    "aggregate_throughput_mbps": kpi_b["aggregate_throughput_mbps"],
                    "mean_latency_ms": kpi_b["mean_latency_ms"],
                    "p95_latency_ms": kpi_b["p95_latency_ms"],
                    "packet_loss_pct": kpi_b["packet_loss_pct"],
                    "fairness_index": kpi_b["fairness_index"],
                    "max_ap_load": kpi_b["max_ap_load"]
                }
            })

        return {"duration_min": duration_min, "timeline": timeline}

    def generate_findings_and_recommendations(self, results_a: Dict[str, Any],
                                             results_b: Dict[str, Any],
                                             scenario_name: str) -> Dict[str, Any]:
        """
        Generates quantitative findings and engineering recommendations based on simulation outputs.
        """
        t_a = results_a["avg_throughput_mbps"]["mean"]
        t_b = results_b["avg_throughput_mbps"]["mean"]
        p5_a = results_a["p5_throughput_mbps"]["mean"]
        p5_b = results_b["p5_throughput_mbps"]["mean"]
        lat_a = results_a["mean_latency_ms"]["mean"]
        lat_b = results_b["mean_latency_ms"]["mean"]
        loss_a = results_a["packet_loss_pct"]["mean"]
        loss_b = results_b["packet_loss_pct"]["mean"]
        fair_a = results_a["fairness_index"]["mean"]
        fair_b = results_b["fairness_index"]["mean"]
        cost_a = results_a["total_capex_usd"]
        cost_b = results_b["total_capex_usd"]
        cost_u_a = results_a["cost_per_supported_user_usd"]["mean"]
        cost_u_b = results_b["cost_per_supported_user_usd"]["mean"]

        # Calculate percentage gains
        p5_gain_pct = ((p5_b - p5_a) / max(0.01, p5_a)) * 100.0
        avg_gain_pct = ((t_b - t_a) / max(0.01, t_a)) * 100.0
        lat_reduction_pct = ((lat_a - lat_b) / max(0.01, lat_a)) * 100.0
        cost_diff_pct = ((cost_b - cost_a) / max(1.0, cost_a)) * 100.0

        key_findings = [
            f"Config B improves 5th-percentile (worst-served users) throughput by {p5_gain_pct:+.1f}% ({p5_a:.2f} Mbps -> {p5_b:.2f} Mbps) due to microcell spatial reuse and load balancing.",
            f"Mean latency is reduced by {lat_reduction_pct:.1f}% ({lat_a:.1f} ms -> {lat_b:.1f} ms) in Config B by avoiding 2.4 GHz airtime contention collapse.",
            f"Packet loss drops from {loss_a:.2f}% in Config A down to {loss_b:.2f}% in Config B due to localized collision domains and 5 GHz band steering.",
            f"Jain's Fairness Index improves from {fair_a:.3f} to {fair_b:.3f}, ensuring consistent QoS across high-density platform queues.",
            f"Initial deployment CapEx is {cost_diff_pct:+.1f}% higher for Config B (${cost_b:,.0f} vs ${cost_a:,.0f}), but cost per actually supported user changes from ${cost_u_a:.2f} to ${cost_u_b:.2f}."
        ]

        if p5_gain_pct > 50:
            recommendation_text = (
                f"RECOMMENDATION: Deploy CONFIG B (High-Density Microcell). Under {scenario_name} conditions, "
                f"Config A suffers severe CSMA/CA airtime starvation and co-channel interference on 2.4 GHz. "
                f"Config B provides {p5_gain_pct:+.0f}% higher worst-case throughput and {lat_reduction_pct:.0f}% lower latency, "
                f"making the +{cost_diff_pct:.0f}% hardware investment essential for passenger satisfaction and high SLA compliance."
            )
        else:
            recommendation_text = (
                f"RECOMMENDATION: For lower traffic volumes, Config A is economical. However, for future-proof scalability "
                f"and surge protection during train arrivals, Config B remains the recommended architecture."
            )

        return {
            "summary_statement": f"Config B achieves {p5_gain_pct:+.1f}% better worst-user throughput at {cost_diff_pct:+.1f}% initial CapEx difference.",
            "key_findings": key_findings,
            "recommendation": recommendation_text,
            "p5_gain_pct": round(p5_gain_pct, 1),
            "lat_reduction_pct": round(lat_reduction_pct, 1),
            "avg_gain_pct": round(avg_gain_pct, 1),
            "cost_diff_pct": round(cost_diff_pct, 1)
        }

    def start_simulation_job(self, params: Dict[str, Any]) -> str:
        """Starts a background simulation job and returns the unique job_id."""
        job_id = str(uuid.uuid4())
        with self.lock:
            self.jobs[job_id] = {
                "id": job_id,
                "status": "QUEUED",
                "progress": 0.0,
                "message": "Initializing simulation...",
                "created_at": time.time(),
                "results": None,
                "error": None
            }

        thread = threading.Thread(target=self._execute_job_thread, args=(job_id, params), daemon=True)
        thread.start()
        return job_id

    def _execute_job_thread(self, job_id: str, params: Dict[str, Any]) -> None:
        """Background worker thread executing the complete simulation pipeline."""
        try:
            with self.lock:
                self.jobs[job_id]["status"] = "RUNNING"
                self.jobs[job_id]["progress"] = 5.0
                self.jobs[job_id]["message"] = "Building station models and AP topologies..."

            scenario_key = params.get("scenario", "normal")
            num_users = params.get("users", None)
            trials_count = int(params.get("trials", 25))
            seed = int(params.get("seed", 42))

            # Custom APs if provided from drag-and-drop
            custom_aps_a = None
            if "aps_a" in params:
                custom_aps_a = [AccessPoint(**item) for item in params["aps_a"]]
            custom_aps_b = None
            if "aps_b" in params:
                custom_aps_b = [AccessPoint(**item) for item in params["aps_b"]]

            # 1. Run Config A Monte Carlo
            def prog_a(pct, msg):
                with self.lock:
                    self.jobs[job_id]["progress"] = 5.0 + (pct * 0.40)
                    self.jobs[job_id]["message"] = f"Simulating Config A: {msg}"

            results_a = self.run_monte_carlo(
                config_type="config_a",
                custom_aps=custom_aps_a,
                scenario_key=scenario_key,
                num_users=num_users,
                num_trials=trials_count,
                seed=seed,
                progress_callback=prog_a
            )

            # 2. Run Config B Monte Carlo
            def prog_b(pct, msg):
                with self.lock:
                    self.jobs[job_id]["progress"] = 45.0 + (pct * 0.40)
                    self.jobs[job_id]["message"] = f"Simulating Config B: {msg}"

            results_b = self.run_monte_carlo(
                config_type="config_b",
                custom_aps=custom_aps_b,
                scenario_key=scenario_key,
                num_users=num_users,
                num_trials=trials_count,
                seed=seed + 100,
                progress_callback=prog_b
            )

            # 3. Run 60-Minute Dynamic Time-Series
            with self.lock:
                self.jobs[job_id]["progress"] = 88.0
                self.jobs[job_id]["message"] = "Computing 60-minute dynamic timeline & train burst..."

            default_aps_a = custom_aps_a or APPlacementEngine.get_default_config_a(self.config)
            default_aps_b = custom_aps_b or APPlacementEngine.get_default_config_b(self.config)
            time_series = self.run_time_series(default_aps_a, default_aps_b, duration_min=60, seed=seed)

            # 4. Generate Findings & Recommendations
            with self.lock:
                self.jobs[job_id]["progress"] = 96.0
                self.jobs[job_id]["message"] = "Generating findings and analytics..."

            findings = self.generate_findings_and_recommendations(results_a, results_b, scenario_key.capitalize())

            # Package complete results
            final_results = {
                "scenario_key": scenario_key,
                "config_a": results_a,
                "config_b": results_b,
                "time_series": time_series,
                "findings": findings,
                "aps_a": [{"id": a.id, "name": a.name, "x": a.x, "y": a.y, "tx_power_dbm": a.tx_power_dbm, "channel_24": a.channel_24, "channel_5": a.channel_5} for a in default_aps_a],
                "aps_b": [{"id": b.id, "name": b.name, "x": b.x, "y": b.y, "tx_power_dbm": b.tx_power_dbm, "channel_24": b.channel_24, "channel_5": b.channel_5} for b in default_aps_b],
            }

            with self.lock:
                self.jobs[job_id]["status"] = "COMPLETED"
                self.jobs[job_id]["progress"] = 100.0
                self.jobs[job_id]["message"] = "Simulation complete!"
                self.jobs[job_id]["results"] = final_results

        except Exception as e:
            with self.lock:
                self.jobs[job_id]["status"] = "FAILED"
                self.jobs[job_id]["error"] = str(e)
                self.jobs[job_id]["message"] = f"Simulation failed: {str(e)}"

    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Returns current status and progress of a background job."""
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return None
            return {
                "id": job["id"],
                "status": job["status"],
                "progress": round(job["progress"], 1),
                "message": job["message"],
                "error": job["error"],
                "has_results": job["results"] is not None
            }

    def get_job_results(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Returns completed results of a background job."""
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job["status"] != "COMPLETED":
                return None
            return job["results"]

    @staticmethod
    def export_ns3_scenario(config_name: str, aps: List[AccessPoint],
                            station_width: float, station_height: float) -> str:
        """
        Generates an NS-3 C++ / Python simulation script definition for the scenario.
        """
        code = [
            f"// ===========================================================================",
            f"// NS-3 Simulation Script - StationWiFi Lab Export",
            f"// Configuration: {config_name.upper()}",
            f"// Floorplan: {station_width}m x {station_height}m Concourse + 4 Platforms",
            f"// ===========================================================================",
            f'#include "ns3/core-module.h"',
            f'#include "ns3/network-module.h"',
            f'#include "ns3/mobility-module.h"',
            f'#include "ns3/wifi-module.h"',
            f'#include "ns3/internet-module.h"',
            f'#include "ns3/applications-module.h"',
            f'',
            f'using namespace ns3;',
            f'',
            f'NS_LOG_COMPONENT_DEFINE("StationWiFi_{config_name}");',
            f'',
            f'int main(int argc, char *argv[]) {{',
            f'    uint32_t nAps = {len(aps)};',
            f'    CommandLine cmd;',
            f'    cmd.Parse(argc, argv);',
            f'',
            f'    // 1. Create AP Nodes',
            f'    NodeContainer wifiApNodes;',
            f'    wifiApNodes.Create(nAps);',
            f'',
            f'    // 2. Set AP Mobility and Coordinates',
            f'    MobilityHelper mobility;',
            f'    Ptr<ListPositionAllocator> positionAlloc = CreateObject<ListPositionAllocator>();',
        ]

        for ap in aps:
            code.append(f'    positionAlloc->Add(Vector({ap.x:.1f}, {ap.y:.1f}, {ap.height_m:.1f})); // {ap.name}')

        code.extend([
            f'    mobility.SetPositionAllocator(positionAlloc);',
            f'    mobility.SetMobilityModel("ns3::ConstantPositionMobilityModel");',
            f'    mobility.Install(wifiApNodes);',
            f'',
            f'    // 3. Configure YansWifiChannel with LogDistance & Obstacle Loss',
            f'    YansWifiChannelHelper channel = YansWifiChannelHelper::Default();',
            f'    channel.AddPropagationLoss("ns3::LogDistancePropagationLossModel",',
            f'                               "Exponent", DoubleValue(3.2),',
            f'                               "ReferenceDistance", DoubleValue(1.0));',
            f'    channel.AddPropagationLoss("ns3::RandomPropagationLossModel");',
            f'',
            f'    YansWifiPhyHelper phy;',
            f'    phy.SetChannel(channel.Create());',
            f'',
            f'    // 4. Configure Wi-Fi Standard (802.11ac / 802.11ax)',
            f'    WifiHelper wifi;',
            f'    wifi.SetStandard(WIFI_STANDARD_80211ac);',
            f'    wifi.SetRemoteStationManager("ns3::MinstrelHtWifiManager");',
            f'',
            f'    WifiMacHelper mac;',
            f'    Ssid ssid = Ssid("StationFreeWiFi");',
            f'    mac.SetType("ns3::ApWifiMac", "Ssid", SsidValue(ssid));',
            f'',
            f'    NetDeviceContainer apDevices = wifi.Install(phy, mac, wifiApNodes);',
            f'',
            f'    // 5. Run NS-3 Simulation',
            f'    Simulator::Stop(Seconds(60.0));',
            f'    Simulator::Run();',
            f'    Simulator::Destroy();',
            f'    return 0;',
            f'}}'
        ])
        return "\n".join(code)
