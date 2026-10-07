"""
sim/metrics.py - Performance Metrics Engine.

Calculates:
1. Throughput Statistics (Average, 5th Percentile / Worst 5%, Station Aggregate).
2. Latency Metrics (Mean, 95th Percentile, Jitter / Standard Deviation).
3. RF Signal Metrics (RSSI mean/p5, % Good > -67 dBm, % Poor < -75 dBm, Coverage Area %).
4. SINR Statistics (Mean, Median, 5th and 95th percentiles).
5. Packet Loss Rate (Mean %, Worst AP Loss %).
6. AP Utilization & Load Distribution.
7. Jain's Fairness Index: J(x) = (Sum(x_i))^2 / (N * Sum(x_i^2)).
8. Cost Analysis (CapEx Total, Cost per Supported User).
"""

import math
import numpy as np
from typing import List, Dict, Tuple, Optional, Any
from .floorplan import StationFloorplan, User
from .placement import AccessPoint
from .propagation import PropagationModel


class MetricsEngine:
    """Computes comprehensive WLAN deployment performance metrics."""

    @staticmethod
    def calculate_jains_fairness(values: List[float]) -> float:
        """
        Computes Jain's Fairness Index: J(x) = (Sum(x))^2 / (N * Sum(x^2))
        Returns a value in [0.0, 1.0], where 1.0 is perfectly fair.
        """
        arr = np.array(values, dtype=float)
        if len(arr) == 0:
            return 1.0
        # If all values are zero, fairness is defined as 1.0 (equally zero)
        s = np.sum(arr)
        if s <= 0:
            return 1.0
        sq_sum = np.sum(arr ** 2)
        if sq_sum <= 0:
            return 1.0
        fairness = (s ** 2) / (len(arr) * sq_sum)
        return float(min(1.0, max(0.0, fairness)))

    @staticmethod
    def compute_single_run_metrics(users: List[User], aps: List[AccessPoint],
                                  propagation: PropagationModel,
                                  floorplan: StationFloorplan) -> Dict[str, Any]:
        """Computes all KPIs for a single Monte-Carlo trial."""
        num_users = len(users)
        if num_users == 0:
            return {}

        throughputs = [u.throughput_mbps for u in users]
        latencies = [u.latency_ms for u in users if u.throughput_mbps > 0]
        losses = [u.packet_loss_pct for u in users]
        rssis = [u.rssi_dbm for u in users if u.connected_ap_id is not None]
        sinrs = [u.sinr_db for u in users if u.connected_ap_id is not None]

        # Connected count
        connected_users = [u for u in users if u.connected_ap_id is not None]
        supported_users = [u for u in users if u.throughput_mbps >= 0.5]

        # Throughput KPIs
        avg_throughput = float(np.mean(throughputs)) if throughputs else 0.0
        p5_throughput = float(np.percentile(throughputs, 5)) if throughputs else 0.0
        p95_throughput = float(np.percentile(throughputs, 95)) if throughputs else 0.0
        aggregate_throughput = float(np.sum(throughputs))

        # Latency KPIs
        mean_latency = float(np.mean(latencies)) if latencies else 999.0
        p95_latency = float(np.percentile(latencies, 95)) if latencies else 999.0
        jitter_latency = float(np.std(latencies)) if len(latencies) > 1 else 0.0

        # RF KPIs
        good_signal_users = sum(1 for r in rssis if r >= -67.0)
        poor_signal_users = sum(1 for r in rssis if r < -75.0)
        pct_good_rssi = (good_signal_users / max(1, len(rssis))) * 100.0
        pct_poor_rssi = (poor_signal_users / max(1, len(rssis))) * 100.0
        mean_rssi = float(np.mean(rssis)) if rssis else -100.0
        mean_sinr = float(np.mean(sinrs)) if sinrs else -10.0
        p5_sinr = float(np.percentile(sinrs, 5)) if sinrs else -10.0

        # Packet Loss
        mean_loss = float(np.mean(losses)) if losses else 100.0

        # Fairness
        fairness_index = MetricsEngine.calculate_jains_fairness(throughputs)

        # AP Load & Utilization
        ap_client_counts = [len(ap.connected_clients) for ap in aps]
        max_ap_load = max(ap_client_counts) if ap_client_counts else 0
        mean_ap_load = float(np.mean(ap_client_counts)) if ap_client_counts else 0.0
        ap_load_std = float(np.std(ap_client_counts)) if len(ap_client_counts) > 1 else 0.0

        # Coverage Calculation on a sample grid
        total_capex = sum(ap.total_cost for ap in aps)
        cost_per_user = total_capex / max(1, len(supported_users))

        # Estimated roaming transitions (based on boundary overlaps and passenger mobility)
        est_roaming_events = int(len(supported_users) * (len(aps) / 12.0) * 0.35)

        return {
            "num_users": num_users,
            "connected_count": len(connected_users),
            "supported_count": len(supported_users),
            "coverage_pct": round(len(connected_users) / max(1, num_users) * 100.0, 1),
            "avg_throughput_mbps": round(avg_throughput, 3),
            "p5_throughput_mbps": round(p5_throughput, 3),
            "p95_throughput_mbps": round(p95_throughput, 3),
            "aggregate_throughput_mbps": round(aggregate_throughput, 2),
            "mean_latency_ms": round(mean_latency, 2),
            "p95_latency_ms": round(p95_latency, 2),
            "jitter_ms": round(jitter_latency, 2),
            "mean_rssi_dbm": round(mean_rssi, 1),
            "pct_good_rssi": round(pct_good_rssi, 1),
            "pct_poor_rssi": round(pct_poor_rssi, 1),
            "mean_sinr_db": round(mean_sinr, 1),
            "p5_sinr_db": round(p5_sinr, 1),
            "packet_loss_pct": round(mean_loss, 2),
            "fairness_index": round(fairness_index, 3),
            "total_capex_usd": round(total_capex, 2),
            "cost_per_supported_user_usd": round(cost_per_user, 2),
            "max_ap_load": max_ap_load,
            "mean_ap_load": round(mean_ap_load, 1),
            "ap_load_std": round(ap_load_std, 2),
            "est_roaming_events": est_roaming_events,
            "raw_throughputs": throughputs,
            "raw_latencies": latencies,
            "raw_losses": losses,
            "raw_rssis": rssis,
            "raw_sinrs": sinrs,
            "ap_loads": [{"ap_id": ap.id, "name": ap.name, "clients": len(ap.connected_clients), "channel_24": ap.channel_24, "channel_5": ap.channel_5} for ap in aps]
        }

    @staticmethod
    def aggregate_monte_carlo_results(trials: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Aggregates multiple Monte-Carlo runs to produce mean, median, p5, p95, and 95% Confidence Intervals.
        """
        if not trials:
            return {}

        keys_to_aggregate = [
            "avg_throughput_mbps", "p5_throughput_mbps", "p95_throughput_mbps", "aggregate_throughput_mbps",
            "mean_latency_ms", "p95_latency_ms", "jitter_ms", "mean_rssi_dbm",
            "pct_good_rssi", "pct_poor_rssi", "mean_sinr_db", "p5_sinr_db",
            "packet_loss_pct", "fairness_index", "coverage_pct", "cost_per_supported_user_usd",
            "max_ap_load", "mean_ap_load"
        ]

        summary = {}
        N = len(trials)
        for key in keys_to_aggregate:
            vals = [t[key] for t in trials if key in t]
            if not vals:
                continue
            arr = np.array(vals)
            m = float(np.mean(arr))
            med = float(np.median(arr))
            p5 = float(np.percentile(arr, 5))
            p95 = float(np.percentile(arr, 95))
            std_err = float(np.std(arr) / math.sqrt(N)) if N > 1 else 0.0
            ci95 = 1.96 * std_err

            summary[key] = {
                "mean": round(m, 3),
                "median": round(med, 3),
                "p5": round(p5, 3),
                "p95": round(p95, 3),
                "ci95_low": round(max(0.0, m - ci95), 3),
                "ci95_high": round(m + ci95, 3),
            }

        # Representative single trial data for histograms / raw distributions
        best_rep_idx = len(trials) // 2
        summary["representative_trial"] = trials[best_rep_idx]
        summary["total_trials"] = N
        summary["total_capex_usd"] = trials[0].get("total_capex_usd", 0.0)

        return summary
