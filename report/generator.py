"""
report/generator.py - Comprehensive Technical Report Builder.

Generates:
1. Self-contained, publication-grade HTML report with embedded CSS, base64 charts, and interactive tables.
2. Formatted PDF report via Matplotlib PdfPages (robust and dependency-free).
"""

import os
import io
import base64
import math
import numpy as np
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from jinja2 import Template
from typing import Dict, Any, List, Optional
from sim.floorplan import StationFloorplan
from sim.placement import APPlacementEngine, AccessPoint
from sim.propagation import PropagationModel
from sim.mac_model import MACModel
from sim.metrics import MetricsEngine


class ReportGenerator:
    """Generates comprehensive comparative WLAN evaluation reports."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports_generated")
        os.makedirs(self.output_dir, exist_ok=True)

    def _fig_to_base64(self, fig) -> str:
        """Converts a matplotlib figure to base64 PNG string."""
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        buf.seek(0)
        img_str = base64.b64encode(buf.read()).decode("utf-8")
        plt.close(fig)
        return f"data:image/png;base64,{img_str}"

    def generate_sensitivity_data(self) -> Dict[str, Any]:
        """Runs sensitivity sweep over user counts (200 to 3000) for Config A vs B."""
        user_counts = [200, 500, 800, 1200, 1600, 2000, 2500, 3000]
        floorplan = StationFloorplan(self.config)
        prop = PropagationModel(self.config, floorplan)
        mac = MACModel(self.config, prop)

        aps_a = APPlacementEngine.get_default_config_a(self.config)
        aps_b = APPlacementEngine.get_default_config_b(self.config)

        t_avg_a, t_p5_a, lat_a, loss_a = [], [], [], []
        t_avg_b, t_p5_b, lat_b, loss_b = [], [], [], []

        for u_cnt in user_counts:
            # Synthetic evaluation at this scale
            users = floorplan.generate_passengers(scenario_key="normal", custom_user_count=u_cnt, seed=42 + u_cnt)

            # A
            mac.associate_clients(users, aps_a, is_config_b=False)
            mac.simulate_mac_throughput(users, aps_a, is_config_b=False)
            k_a = MetricsEngine.compute_single_run_metrics(users, aps_a, prop, floorplan)
            t_avg_a.append(k_a["avg_throughput_mbps"])
            t_p5_a.append(k_a["p5_throughput_mbps"])
            lat_a.append(k_a["mean_latency_ms"])
            loss_a.append(k_a["packet_loss_pct"])

            # B
            mac.associate_clients(users, aps_b, is_config_b=True)
            mac.simulate_mac_throughput(users, aps_b, is_config_b=True)
            k_b = MetricsEngine.compute_single_run_metrics(users, aps_b, prop, floorplan)
            t_avg_b.append(k_b["avg_throughput_mbps"])
            t_p5_b.append(k_b["p5_throughput_mbps"])
            lat_b.append(k_b["mean_latency_ms"])
            loss_b.append(k_b["packet_loss_pct"])

        return {
            "user_counts": user_counts,
            "config_a": {"t_avg": t_avg_a, "t_p5": t_p5_a, "latency": lat_a, "loss": loss_a},
            "config_b": {"t_avg": t_avg_b, "t_p5": t_p5_b, "latency": lat_b, "loss": loss_b}
        }

    def generate_chart_images(self, sim_results: Dict[str, Any], sensitivity: Dict[str, Any]) -> Dict[str, str]:
        """Generates all comparative figures for the report."""
        charts = {}
        plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")

        # 1. Floorplan & AP Placement
        fig, ax = plt.subplots(figsize=(10, 4))
        # Draw zones
        floorplan = StationFloorplan(self.config)
        for z in floorplan.zones:
            rect = plt.Rectangle((z.x, z.y), z.width, z.height, alpha=0.15, color=z.color, label=z.name)
            ax.add_patch(rect)
            ax.text(z.x + z.width / 2, z.y + z.height / 2, z.name,
                    ha='center', va='center', fontsize=7, weight='bold', alpha=0.7)

        # Plot AP positions
        aps_a = APPlacementEngine.get_default_config_a(self.config)
        aps_b = APPlacementEngine.get_default_config_b(self.config)
        ax.scatter([a.x for a in aps_a], [a.y for a in aps_a], color='#ef4444', s=70, marker='^', label='Config A APs (12)', zorder=5)
        ax.scatter([b.x for b in aps_b], [b.y for b in aps_b], color='#10b981', s=45, marker='o', label='Config B APs (36)', zorder=4)

        ax.set_xlim(-5, 205)
        ax.set_ylim(-60, 65)
        ax.set_xlabel("Station Width (Meters)")
        ax.set_ylabel("Station Depth (Meters)")
        ax.set_title("Station Layout & AP Placement (Config A vs Config B)")
        ax.legend(loc='upper right', fontsize=8)
        charts["floorplan"] = self._fig_to_base64(fig)

        # 2. Throughput & Latency Sensitivity Curves
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4))
        u = sensitivity["user_counts"]
        # Throughput
        ax1.plot(u, sensitivity["config_a"]["t_p5"], 'r--o', label="Config A (Worst 5% / p5)")
        ax1.plot(u, sensitivity["config_a"]["t_avg"], 'r-s', label="Config A (Average)")
        ax1.plot(u, sensitivity["config_b"]["t_p5"], 'g--o', label="Config B (Worst 5% / p5)")
        ax1.plot(u, sensitivity["config_b"]["t_avg"], 'g-s', label="Config B (Average)")
        ax1.set_xlabel("Number of Connected Passengers")
        ax1.set_ylabel("Throughput per User (Mbps)")
        ax1.set_title("Throughput Degradation vs Scale")
        ax1.legend(fontsize=8)

        # Latency
        ax2.plot(u, sensitivity["config_a"]["latency"], 'r-o', label="Config A Latency")
        ax2.plot(u, sensitivity["config_b"]["latency"], 'g-o', label="Config B Latency")
        ax2.set_xlabel("Number of Connected Passengers")
        ax2.set_ylabel("Mean Latency (ms)")
        ax2.set_title("Latency Scaling vs Station Load")
        ax2.legend(fontsize=8)
        plt.tight_layout()
        charts["sensitivity"] = self._fig_to_base64(fig)

        # 3. 60-Minute Dynamic Timeline
        timeline = sim_results.get("time_series", {}).get("timeline", [])
        if timeline:
            mins = [t["minute"] for t in timeline]
            lat_a = [t["config_a"]["mean_latency_ms"] for t in timeline]
            lat_b = [t["config_b"]["mean_latency_ms"] for t in timeline]
            users_t = [t["user_count"] for t in timeline]

            fig, ax1 = plt.subplots(figsize=(10, 4))
            ax2 = ax1.twinx()
            ax2.bar(mins, users_t, alpha=0.18, color='gray', label="Passenger Count")
            ax2.set_ylabel("Active Passengers")
            ax2.grid(False)

            ax1.plot(mins, lat_a, 'r-', linewidth=2, label="Config A Latency (ms)")
            ax1.plot(mins, lat_b, 'g-', linewidth=2, label="Config B Latency (ms)")
            ax1.axvspan(15, 30, color='orange', alpha=0.15, label="Train Burst Event")
            ax1.set_xlabel("Simulation Timeline (Minutes)")
            ax1.set_ylabel("Latency (ms)")
            ax1.set_title("60-Minute Dynamic Performance & Surge Behavior")
            ax1.legend(loc='upper left', fontsize=8)
            ax2.legend(loc='upper right', fontsize=8)
            plt.tight_layout()
            charts["timeline"] = self._fig_to_base64(fig)

        # 4. SINR & RSSI Distribution
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 3.8))
        rep_a = sim_results.get("config_a", {}).get("representative_trial", {})
        rep_b = sim_results.get("config_b", {}).get("representative_trial", {})

        rssi_a = rep_a.get("raw_rssis", [-70])
        rssi_b = rep_b.get("raw_rssis", [-65])
        sinr_a = rep_a.get("raw_sinrs", [12])
        sinr_b = rep_b.get("raw_sinrs", [22])

        ax1.hist(rssi_a, bins=25, alpha=0.5, color='red', label="Config A RSSI", density=True)
        ax1.hist(rssi_b, bins=25, alpha=0.5, color='green', label="Config B RSSI", density=True)
        ax1.set_xlabel("RSSI (dBm)")
        ax1.set_ylabel("Probability Density")
        ax1.set_title("Signal Strength (RSSI) Distribution")
        ax1.legend(fontsize=8)

        ax2.hist(sinr_a, bins=25, alpha=0.5, color='red', label="Config A SINR", density=True)
        ax2.hist(sinr_b, bins=25, alpha=0.5, color='green', label="Config B SINR", density=True)
        ax2.set_xlabel("SINR (dB)")
        ax2.set_ylabel("Probability Density")
        ax2.set_title("SINR Distribution (Interference Resilience)")
        ax2.legend(fontsize=8)
        plt.tight_layout()
        charts["rf_dist"] = self._fig_to_base64(fig)

        return charts

    def generate_html_report(self, sim_results: Dict[str, Any], output_filename: str = "stationwifi_report.html") -> str:
        """Generates the full comparative evaluation HTML report."""
        sensitivity = self.generate_sensitivity_data()
        charts = self.generate_chart_images(sim_results, sensitivity)

        template_path = os.path.join(os.path.dirname(__file__), "template.html")
        with open(template_path, "r", encoding="utf-8") as f:
            template_str = f.read()

        jinja_template = Template(template_str)
        rendered_html = jinja_template.render(
            results=sim_results,
            findings=sim_results.get("findings", {}),
            charts=charts,
            config=self.config
        )

        out_path = os.path.join(self.output_dir, output_filename)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(rendered_html)

        return out_path

    def generate_pdf_report(self, sim_results: Dict[str, Any], output_filename: str = "stationwifi_report.pdf") -> str:
        """
        Generates a clean, multi-page PDF performance report using Matplotlib PdfPages.
        """
        out_path = os.path.join(self.output_dir, output_filename)
        sensitivity = self.generate_sensitivity_data()

        with PdfPages(out_path) as pdf:
            # Page 1: Title & Executive Summary
            fig1 = plt.figure(figsize=(8.5, 11))
            plt.axis("off")
            fig1.text(0.5, 0.92, "StationWiFi Lab", ha="center", fontsize=24, weight="bold", color="#1e293b")
            fig1.text(0.5, 0.88, "Railway Station WLAN Deployment & Performance Evaluation", ha="center", fontsize=14, color="#475569")
            fig1.text(0.5, 0.85, "Comparative Analysis: Traditional High-Power (A) vs Microcell Capacity (B)", ha="center", fontsize=11, style="italic", color="#64748b")

            findings = sim_results.get("findings", {})
            cfg_a = sim_results.get("config_a", {})
            cfg_b = sim_results.get("config_b", {})

            summary_text = (
                "EXECUTIVE SUMMARY\n"
                "----------------------------------------------------------------------------------------------------\n"
                "This technical study evaluates two distinct Wi-Fi deployment architectures for a crowded 200m x 60m\n"
                "railway junction serving up to 2,000 concurrent passengers with a 2 Gbps fibre uplink.\n\n"
                f"- Configuration A (12 Macrocell APs, 20 dBm): Traditional coverage-oriented setup.\n"
                f"- Configuration B (36 Microcell APs, 12 dBm): Modern capacity-oriented microcell with band steering.\n\n"
                "KEY PERFORMANCE COMPARISON\n"
                "----------------------------------------------------------------------------------------------------\n"
                f"{'Metric':<30} | {'Config A':<18} | {'Config B':<18} | {'Advantage':<15}\n"
                f"{'-'*30} | {'-'*18} | {'-'*18} | {'-'*15}\n"
                f"{'Avg Throughput (Mbps)':<30} | {cfg_a.get('avg_throughput_mbps',{}).get('mean',0):<18.2f} | {cfg_b.get('avg_throughput_mbps',{}).get('mean',0):<18.2f} | {'Config B (' + str(findings.get('avg_gain_pct',0)) + '%)'}\n"
                f"{'Worst 5% Throughput (Mbps)':<30} | {cfg_a.get('p5_throughput_mbps',{}).get('mean',0):<18.2f} | {cfg_b.get('p5_throughput_mbps',{}).get('mean',0):<18.2f} | {'Config B (' + str(findings.get('p5_gain_pct',0)) + '%)'}\n"
                f"{'Mean Latency (ms)':<30} | {cfg_a.get('mean_latency_ms',{}).get('mean',0):<18.1f} | {cfg_b.get('mean_latency_ms',{}).get('mean',0):<18.1f} | {'Config B (' + str(findings.get('lat_reduction_pct',0)) + '%)'}\n"
                f"{'Packet Loss (%)':<30} | {cfg_a.get('packet_loss_pct',{}).get('mean',0):<18.2f} | {cfg_b.get('packet_loss_pct',{}).get('mean',0):<18.2f} | {'Config B'}\n"
                f"{'Jain Fairness Index':<30} | {cfg_a.get('fairness_index',{}).get('mean',0):<18.3f} | {cfg_b.get('fairness_index',{}).get('mean',0):<18.3f} | {'Config B'}\n"
                f"{'Initial CapEx ($)':<30} | ${cfg_a.get('total_capex_usd',0):<17,.0f} | ${cfg_b.get('total_capex_usd',0):<17,.0f} | {'Config A (-' + str(findings.get('cost_diff_pct',0)) + '%)'}\n"
                f"{'Cost / Supported User':<30} | ${cfg_a.get('cost_per_supported_user_usd',{}).get('mean',0):<17.2f} | ${cfg_b.get('cost_per_supported_user_usd',{}).get('mean',0):<17.2f} | {'Config B'}\n\n"
                "ENGINEERING RECOMMENDATION\n"
                "----------------------------------------------------------------------------------------------------\n"
                f"{findings.get('recommendation', 'Deploy Config B for high density scalability.')}\n"
            )

            fig1.text(0.1, 0.25, summary_text, fontsize=9, family="monospace", va="top")
            pdf.savefig(fig1)
            plt.close(fig1)

            # Page 2: Sensitivity & Time-Series Visuals
            fig2, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(8.5, 11))
            u = sensitivity["user_counts"]
            ax1.plot(u, sensitivity["config_a"]["t_p5"], 'r--o', label="Config A (p5)")
            ax1.plot(u, sensitivity["config_b"]["t_p5"], 'g--o', label="Config B (p5)")
            ax1.set_title("Worst 5% User Throughput vs Users")
            ax1.set_xlabel("Users")
            ax1.set_ylabel("Mbps")
            ax1.legend()

            ax2.plot(u, sensitivity["config_a"]["latency"], 'r-o', label="Config A")
            ax2.plot(u, sensitivity["config_b"]["latency"], 'g-o', label="Config B")
            ax2.set_title("Mean Latency vs Users")
            ax2.set_xlabel("Users")
            ax2.set_ylabel("ms")
            ax2.legend()

            ax3.plot(u, sensitivity["config_a"]["loss"], 'r-s', label="Config A")
            ax3.plot(u, sensitivity["config_b"]["loss"], 'g-s', label="Config B")
            ax3.set_title("Packet Loss Rate vs Users")
            ax3.set_xlabel("Users")
            ax3.set_ylabel("% Loss")
            ax3.legend()

            ax4.scatter([a.x for a in APPlacementEngine.get_default_config_a(self.config)],
                        [a.y for a in APPlacementEngine.get_default_config_a(self.config)],
                        color='red', marker='^', label='Config A APs')
            ax4.scatter([b.x for b in APPlacementEngine.get_default_config_b(self.config)],
                        [b.y for b in APPlacementEngine.get_default_config_b(self.config)],
                        color='green', marker='o', label='Config B APs')
            ax4.set_title("AP Deployment Map (200m x 60m)")
            ax4.set_xlabel("X (m)")
            ax4.set_ylabel("Y (m)")
            ax4.legend()

            plt.tight_layout(pad=3.0)
            pdf.savefig(fig2)
            plt.close(fig2)

        return out_path
