"""
sim/mac_model.py - 802.11 PHY Data Rate (MCS), Association Logic, and CSMA/CA MAC Contention Model.
"""

import math
import numpy as np
from typing import List, Dict, Tuple, Optional, Any
from .floorplan import StationFloorplan, User
from .placement import AccessPoint
from .propagation import PropagationModel


# MCS Table: (Min SINR dB, MCS Index, Modulation, Code Rate, Rate 20MHz Mbps, Rate 40MHz Mbps)
MCS_TABLE = [
    (1.0,  0, "BPSK",     "1/2",  8.6,   17.2),
    (4.0,  1, "QPSK",     "1/2",  17.2,  34.4),
    (7.0,  2, "QPSK",     "3/4",  25.8,  51.6),
    (10.0, 3, "16-QAM",   "1/2",  34.4,  68.8),
    (13.0, 4, "16-QAM",   "3/4",  51.6,  103.2),
    (17.0, 5, "64-QAM",   "2/3",  68.8,  137.6),
    (19.0, 6, "64-QAM",   "3/4",  77.4,  154.9),
    (22.0, 7, "64-QAM",   "5/6",  86.0,  172.1),
    (25.0, 8, "256-QAM",  "3/4",  103.2, 206.5),
    (28.0, 9, "256-QAM",  "5/6",  114.7, 229.4),
    (31.0, 10, "1024-QAM", "3/4", 129.0, 258.1),
    (34.0, 11, "1024-QAM", "5/6", 143.4, 286.8),
]


class MACModel:
    """Simulates 802.11 association, PHY rate determination, and CSMA/CA MAC airtime."""

    def __init__(self, config: Dict[str, Any], propagation: PropagationModel):
        self.config = config
        self.propagation = propagation
        mac_cfg = config.get("mac", {})
        self.base_efficiency = float(mac_cfg.get("mac_efficiency", 0.60))
        self.cw_min = int(mac_cfg.get("cw_min", 15))
        self.max_retries = int(mac_cfg.get("max_retries", 7))
        self.backhaul_mbps = float(config.get("station", {}).get("backhaul_gbps", 2.0)) * 1000.0

    def sinr_to_phy_rate(self, sinr_db: float, channel_width_mhz: int = 20) -> Tuple[int, float, float]:
        if sinr_db < MCS_TABLE[0][0]:
            return (-1, 0.0, 1.0)

        selected_mcs = MCS_TABLE[0]
        for mcs_entry in MCS_TABLE:
            if sinr_db >= mcs_entry[0]:
                selected_mcs = mcs_entry
            else:
                break

        mcs_idx = selected_mcs[1]
        phy_rate = selected_mcs[5] if channel_width_mhz >= 40 else selected_mcs[4]
        margin = sinr_db - selected_mcs[0]
        base_per = max(0.005, min(0.35, 0.30 * math.exp(-0.4 * margin)))

        return (mcs_idx, float(phy_rate), float(base_per))

    def associate_clients(self, users: List[User], aps: List[AccessPoint],
                          is_config_b: bool = False,
                          rng: Optional[np.random.Generator] = None) -> None:
        """
        Vectorized high-performance association and SINR engine.
        """
        for ap in aps:
            ap.connected_clients.clear()

        if not users or not aps:
            return

        # Vector of user coordinates
        u_x = np.array([u.x for u in users])
        u_y = np.array([u.y for u in users])
        N = len(users)
        M = len(aps)

        # AP coordinates
        ap_x = np.array([ap.x for ap in aps])
        ap_y = np.array([ap.y for ap in aps])
        ap_h = np.array([ap.height_m for ap in aps])
        ap_tx = np.array([ap.tx_power_dbm for ap in aps])
        ap_gain = np.array([ap.antenna_gain_dbi for ap in aps])
        ap_max_clients = np.array([ap.max_clients for ap in aps])

        # 3D Distance Matrix (N, M)
        dx = u_x[:, None] - ap_x[None, :]
        dy = u_y[:, None] - ap_y[None, :]
        dz = 1.2 - ap_h[None, :]
        dist_3d = np.maximum(1.0, np.sqrt(dx * dx + dy * dy + dz * dz))

        # Obstacle loss matrix
        # For ultra fast vectorized runs, compute wall attenuation on distance
        # Log-distance path loss matrices
        # 2.4 GHz
        pl_24 = self.propagation.pl0_24 + 10.0 * self.propagation.n_24 * np.log10(dist_3d) + 2.0
        rssi_24 = (ap_tx + ap_gain)[None, :] - pl_24

        # 5 GHz
        pl_5 = self.propagation.pl0_5 + 10.0 * self.propagation.n_5 * np.log10(dist_3d) + 3.0
        rssi_5 = (ap_tx + ap_gain)[None, :] - pl_5

        # Add shadowing random variations
        if rng is not None:
            rssi_24 += rng.normal(0, self.propagation.sigma * 0.7, size=(N, M))
            rssi_5 += rng.normal(0, self.propagation.sigma * 0.7, size=(N, M))

        # AP Load tracking
        ap_client_counts = np.zeros(M, dtype=int)

        for i, user in enumerate(users):
            # Select candidate band
            if user.device_type == "5ghz_only":
                target_band = "5GHz"
                user_rssis = rssi_5[i]
            elif user.device_type == "2.4ghz_only":
                target_band = "2.4GHz"
                user_rssis = rssi_24[i]
            else:  # dual_band
                if is_config_b:
                    target_band = "5GHz"
                    user_rssis = rssi_5[i]
                else:
                    target_band = "2.4GHz"
                    user_rssis = rssi_24[i]

            # Sorted AP indices by RSSI descending
            sorted_ap_indices = np.argsort(-user_rssis)
            best_idx = sorted_ap_indices[0]

            if is_config_b:
                # Load balancing: if best AP is full, check next candidate within 8 dB
                best_rssi_val = user_rssis[best_idx]
                for cand_idx in sorted_ap_indices:
                    if ap_client_counts[cand_idx] < ap_max_clients[cand_idx] and (best_rssi_val - user_rssis[cand_idx] <= 8.0):
                        best_idx = cand_idx
                        break

            chosen_ap = aps[best_idx]
            chosen_rssi = float(user_rssis[best_idx])

            if chosen_rssi < -88.0:
                user.connected_ap_id = None
                user.connected_band = None
                user.rssi_dbm = -100.0
                user.sinr_db = -10.0
                user.phy_rate_mbps = 0.0
                continue

            user.connected_ap_id = chosen_ap.id
            user.connected_band = target_band
            user.channel = chosen_ap.channel_5 if target_band == "5GHz" else chosen_ap.channel_24
            user.rssi_dbm = round(chosen_rssi, 2)
            chosen_ap.connected_clients.append(user.id)
            ap_client_counts[best_idx] += 1

            # Compute SINR
            noise_dbm = self.propagation.noise_5_dbm if target_band == "5GHz" else self.propagation.noise_24_dbm
            noise_mw = 10.0 ** (noise_dbm / 10.0)
            sig_mw = 10.0 ** (chosen_rssi / 10.0)

            # Sum co-channel interferers
            int_mw = 0.0
            for other_idx, other_ap in enumerate(aps):
                if other_idx == best_idx:
                    continue
                other_ch = other_ap.channel_5 if target_band == "5GHz" else other_ap.channel_24
                if other_ch == user.channel:
                    int_mw += 10.0 ** (float(user_rssis[other_idx]) / 10.0)

            sinr_db = 10.0 * math.log10(max(1e-4, sig_mw / (noise_mw + int_mw)))
            user.sinr_db = round(sinr_db, 2)

            ch_width = chosen_ap.channel_width_5_mhz if target_band == "5GHz" else chosen_ap.channel_width_24_mhz
            _, phy_rate, _ = self.sinr_to_phy_rate(user.sinr_db, ch_width)
            user.phy_rate_mbps = phy_rate

    def simulate_mac_throughput(self, users: List[User], aps: List[AccessPoint],
                                is_config_b: bool = False,
                                rng: Optional[np.random.Generator] = None) -> None:
        ap_map = {ap.id: ap for ap in aps}
        ap_band_groups: Dict[Tuple[int, str], List[User]] = {}

        for user in users:
            if user.connected_ap_id is None or user.phy_rate_mbps <= 0:
                user.throughput_mbps = 0.0
                user.packet_loss_pct = 100.0
                user.latency_ms = 999.0
                continue

            key = (user.connected_ap_id, user.connected_band)
            if key not in ap_band_groups:
                ap_band_groups[key] = []
            ap_band_groups[key].append(user)

        for (ap_id, band), group_users in ap_band_groups.items():
            K = len(group_users)
            tau = 2.0 / (self.cw_min + 1.0)
            p_collision = 1.0 - ((1.0 - tau) ** max(0, K - 1))
            contention_factor = 1.0 / (1.0 + 0.025 * K)
            effective_mac_eff = self.base_efficiency * (1.0 - 0.45 * p_collision) * contention_factor

            demanded_airtime_sum = sum(u.demand_mbps / max(1.0, u.phy_rate_mbps) for u in group_users)
            airtime_capacity = effective_mac_eff
            utilization = min(1.0, demanded_airtime_sum / max(0.01, airtime_capacity))

            if demanded_airtime_sum <= airtime_capacity:
                for u in group_users:
                    _, _, base_per = self.sinr_to_phy_rate(u.sinr_db)
                    u.throughput_mbps = round(u.demand_mbps * max(0.0, 1.0 - base_per), 3)
                    u.packet_loss_pct = round(base_per * 100.0, 2)
            else:
                scaling = airtime_capacity / demanded_airtime_sum
                for u in group_users:
                    _, _, base_per = self.sinr_to_phy_rate(u.sinr_db)
                    congestion_loss = min(0.60, p_collision * (1.0 - scaling))
                    total_loss = min(0.95, base_per + congestion_loss)
                    fair_throughput = (u.demand_mbps * scaling) * (1.0 - total_loss)
                    u.throughput_mbps = round(max(0.01, fair_throughput), 3)
                    u.packet_loss_pct = round(total_loss * 100.0, 2)

            base_latency = 4.0
            rho = min(0.96, utilization)
            queueing_delay_ms = (rho / (1.0 - rho)) * 8.0 * 0.4
            retry_count = int(p_collision * self.max_retries)
            retry_delay_ms = retry_count * 6.0

            for u in group_users:
                jitter = (rng.uniform(-0.15, 0.15) if rng is not None else 0.0) * queueing_delay_ms
                u.latency_ms = round(max(2.0, base_latency + queueing_delay_ms + retry_delay_ms + jitter), 2)
                u.retransmissions = retry_count

        total_station_achieved = sum(u.throughput_mbps for u in users)
        if total_station_achieved > self.backhaul_mbps:
            backhaul_scaling = self.backhaul_mbps / total_station_achieved
            for u in users:
                u.throughput_mbps = round(u.throughput_mbps * backhaul_scaling, 3)
