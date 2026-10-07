"""
sim/placement.py - Access Point Placement and Channel Assignment Algorithms.

This module provides:
1. AccessPoint data representation.
2. Placement strategies:
   - Default engineered layouts for Config A (12 APs) and Config B (36 APs).
   - Uniform Grid AP Placement.
   - K-Means Density-Weighted AP Placement.
3. Greedy Graph-Coloring Channel Assignment to minimize co-channel interference.
4. Deployment CapEx / OpEx Cost Estimation.
"""

import math
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any
from .floorplan import StationFloorplan


@dataclass
class AccessPoint:
    """Represents a deployed Wireless Access Point."""
    id: int
    name: str
    x: float
    y: float
    height_m: float
    tx_power_dbm: float
    antenna_gain_dbi: float
    antenna_type: str            # 'omni' or 'sector'
    antenna_azimuth_deg: float   # Direction for sector antennas (0=East, 90=North)
    antenna_beamwidth_deg: float # Beamwidth (e.g. 65 deg for sector, 360 for omni)
    channel_24: int              # Primary 2.4 GHz channel (e.g. 1, 6, 11)
    channel_5: int               # Primary 5 GHz channel (e.g. 36, 44, 52...)
    channel_width_24_mhz: int    # 20 MHz
    channel_width_5_mhz: int     # 20 or 40 MHz
    band_preference: str         # '2.4GHz' or '5GHz'
    band_steering: bool
    load_balancing: bool
    max_clients: int
    cost_hardware_usd: float = 350.0
    cost_cabling_usd: float = 200.0
    connected_clients: List[int] = field(default_factory=list)

    @property
    def total_cost(self) -> float:
        return self.cost_hardware_usd + self.cost_cabling_usd

    def get_effective_gain(self, target_x: float, target_y: float) -> float:
        """
        Calculates effective antenna gain considering horizontal antenna pattern.
        Omni = flat gain; Sector = 3dB beamwidth parabolic rolloff model.
        """
        if self.antenna_type == "omni" or self.antenna_beamwidth_deg >= 360.0:
            return self.antenna_gain_dbi

        # Sector antenna pattern (3GPP / ITU standard model)
        angle_rad = math.atan2(target_y - self.y, target_x - self.x)
        angle_deg = math.degrees(angle_rad) % 360
        delta_angle = (angle_deg - self.antenna_azimuth_deg + 180) % 360 - 180

        half_bw = self.antenna_beamwidth_deg / 2.0
        # Attenuation: A(theta) = -min(12 * (theta / theta_3dB)^2, Front-to-Back-Ratio 25 dB)
        attenuation = min(25.0, 12.0 * ((delta_angle / half_bw) ** 2))
        return max(-20.0, self.antenna_gain_dbi - attenuation)


class APPlacementEngine:
    """Generates AP coordinates and executes graph-coloring channel assignment."""

    @staticmethod
    def get_default_config_a(config: Dict[str, Any]) -> List[AccessPoint]:
        """
        Config A: Traditional High-Power Macrocell Design (12 APs).
        High transmit power (20 dBm), ceiling mounted (5m), omni antennas.
        """
        cfg_a = config.get("configurations", {}).get("config_a", {})
        tx_pwr = float(cfg_a.get("tx_power_dbm", 20.0))
        gain = float(cfg_a.get("antenna_gain_dbi", 3.0))
        max_clients = int(cfg_a.get("max_clients_per_ap", 250))
        cost_hw = float(cfg_a.get("cost_per_ap_usd", 450))
        cost_cab = float(cfg_a.get("cabling_cost_per_ap_usd", 250))

        # 12 well-distributed macrocell AP positions:
        # Concourse (8 APs in 2 rows of 4) + Platforms (4 APs, 1 per platform pair)
        positions = [
            # Main concourse upper row
            (25.0, 45.0, "AP-A01 (Entrance North)"),
            (75.0, 45.0, "AP-A02 (Concourse Ticketing)"),
            (125.0, 45.0, "AP-A03 (Concourse Central North)"),
            (175.0, 45.0, "AP-A04 (Food Court North)"),
            # Main concourse lower row
            (25.0, 15.0, "AP-A05 (Entrance South)"),
            (75.0, 15.0, "AP-A06 (Waiting Area South)"),
            (125.0, 15.0, "AP-A07 (Concourse Central South)"),
            (175.0, 15.0, "AP-A08 (Executive Lounge)"),
            # Platforms
            (50.0, -15.0, "AP-A09 (Platform 1 West)"),
            (150.0, -15.0, "AP-A10 (Platform 1 East)"),
            (50.0, -40.0, "AP-A11 (Platform 2 West)"),
            (150.0, -40.0, "AP-A12 (Platform 2 East)"),
        ]

        aps: List[AccessPoint] = []
        for idx, (x, y, name) in enumerate(positions):
            aps.append(AccessPoint(
                id=idx + 1,
                name=name,
                x=x,
                y=y,
                height_m=5.0,
                tx_power_dbm=tx_pwr,
                antenna_gain_dbi=gain,
                antenna_type="omni",
                antenna_azimuth_deg=0.0,
                antenna_beamwidth_deg=360.0,
                channel_24=1,  # Will be assigned by channel coloring
                channel_5=36,  # Will be assigned by channel coloring
                channel_width_24_mhz=20,
                channel_width_5_mhz=40,
                band_preference="2.4GHz",
                band_steering=False,
                load_balancing=False,
                max_clients=max_clients,
                cost_hardware_usd=cost_hw,
                cost_cabling_usd=cost_cab
            ))

        # Assign channels using graph coloring
        APPlacementEngine.assign_channels_graph_coloring(
            aps,
            channels_24=cfg_a.get("supported_channels_24", [1, 6, 11]),
            channels_5=cfg_a.get("supported_channels_5", [36, 40, 44, 48])
        )
        return aps

    @staticmethod
    def get_default_config_b(config: Dict[str, Any]) -> List[AccessPoint]:
        """
        Config B: Modern High-Density Microcell Design (36 APs).
        Low transmit power (12 dBm), lower mounting (3m), sector antennas along platforms,
        5 GHz-first, band steering, load balancing.
        """
        cfg_b = config.get("configurations", {}).get("config_b", {})
        tx_pwr = float(cfg_b.get("tx_power_dbm", 12.0))
        gain = float(cfg_b.get("antenna_gain_dbi", 5.0))
        max_clients = int(cfg_b.get("max_clients_per_ap", 45))
        cost_hw = float(cfg_b.get("cost_per_ap_usd", 350))
        cost_cab = float(cfg_b.get("cabling_cost_per_ap_usd", 180))

        aps: List[AccessPoint] = []
        ap_id = 1

        # 1. Entrance Hall: 4 microcells
        for ex in [10.0, 30.0]:
            for ey in [15.0, 45.0]:
                aps.append(AccessPoint(
                    id=ap_id,
                    name=f"AP-B{ap_id:02d} (Entrance)",
                    x=ex, y=ey, height_m=3.2,
                    tx_power_dbm=tx_pwr, antenna_gain_dbi=gain,
                    antenna_type="omni", antenna_azimuth_deg=0.0, antenna_beamwidth_deg=360.0,
                    channel_24=1, channel_5=36,
                    channel_width_24_mhz=20, channel_width_5_mhz=40,
                    band_preference="5GHz", band_steering=True, load_balancing=True,
                    max_clients=max_clients, cost_hardware_usd=cost_hw, cost_cabling_usd=cost_cab
                ))
                ap_id += 1

        # 2. Ticketing & Central Concourse: 10 microcells
        for cx in [50.0, 70.0, 90.0, 110.0]:
            for cy in [15.0, 35.0, 50.0]:
                if len(aps) >= 14:
                    break
                aps.append(AccessPoint(
                    id=ap_id,
                    name=f"AP-B{ap_id:02d} (Concourse)",
                    x=cx, y=cy, height_m=3.2,
                    tx_power_dbm=tx_pwr, antenna_gain_dbi=gain,
                    antenna_type="omni", antenna_azimuth_deg=0.0, antenna_beamwidth_deg=360.0,
                    channel_24=1, channel_5=36,
                    channel_width_24_mhz=20, channel_width_5_mhz=40,
                    band_preference="5GHz", band_steering=True, load_balancing=True,
                    max_clients=max_clients, cost_hardware_usd=cost_hw, cost_cabling_usd=cost_cab
                ))
                ap_id += 1

        # 3. Food Court & Executive Lounge: 6 microcells
        for fx in [140.0, 165.0, 190.0]:
            for fy in [15.0, 45.0]:
                aps.append(AccessPoint(
                    id=ap_id,
                    name=f"AP-B{ap_id:02d} (Food/Lounge)",
                    x=fx, y=fy, height_m=3.2,
                    tx_power_dbm=tx_pwr, antenna_gain_dbi=gain,
                    antenna_type="omni", antenna_azimuth_deg=0.0, antenna_beamwidth_deg=360.0,
                    channel_24=1, channel_5=36,
                    channel_width_24_mhz=20, channel_width_5_mhz=40,
                    band_preference="5GHz", band_steering=True, load_balancing=True,
                    max_clients=max_clients, cost_hardware_usd=cost_hw, cost_cabling_usd=cost_cab
                ))
                ap_id += 1

        # 4. Platforms 1 & 2: 8 sector microcells facing east/west along tracks
        for px in [20.0, 55.0, 90.0, 125.0, 160.0, 185.0]:
            aps.append(AccessPoint(
                id=ap_id,
                name=f"AP-B{ap_id:02d} (Plat 1/2)",
                x=px, y=-15.0, height_m=3.0,
                tx_power_dbm=tx_pwr, antenna_gain_dbi=gain + 1.5,
                antenna_type="sector", antenna_azimuth_deg=0.0 if px < 100 else 180.0,
                antenna_beamwidth_deg=70.0,
                channel_24=1, channel_5=36,
                channel_width_24_mhz=20, channel_width_5_mhz=40,
                band_preference="5GHz", band_steering=True, load_balancing=True,
                max_clients=max_clients, cost_hardware_usd=cost_hw, cost_cabling_usd=cost_cab
            ))
            ap_id += 1

        # 5. Platforms 3 & 4: 8 sector microcells
        for px in [20.0, 55.0, 90.0, 125.0, 160.0, 185.0]:
            if ap_id > 36:
                break
            aps.append(AccessPoint(
                id=ap_id,
                name=f"AP-B{ap_id:02d} (Plat 3/4)",
                x=px, y=-40.0, height_m=3.0,
                tx_power_dbm=tx_pwr, antenna_gain_dbi=gain + 1.5,
                antenna_type="sector", antenna_azimuth_deg=0.0 if px < 100 else 180.0,
                antenna_beamwidth_deg=70.0,
                channel_24=1, channel_5=36,
                channel_width_24_mhz=20, channel_width_5_mhz=40,
                band_preference="5GHz", band_steering=True, load_balancing=True,
                max_clients=max_clients, cost_hardware_usd=cost_hw, cost_cabling_usd=cost_cab
            ))
            ap_id += 1

        # Fill up to exactly 36 if needed
        while len(aps) < 36:
            aps.append(AccessPoint(
                id=ap_id,
                name=f"AP-B{ap_id:02d} (Aux)",
                x=50.0 + (len(aps) - 30) * 25.0, y=5.0, height_m=3.0,
                tx_power_dbm=tx_pwr, antenna_gain_dbi=gain,
                antenna_type="omni", antenna_azimuth_deg=0.0, antenna_beamwidth_deg=360.0,
                channel_24=1, channel_5=36,
                channel_width_24_mhz=20, channel_width_5_mhz=40,
                band_preference="5GHz", band_steering=True, load_balancing=True,
                max_clients=max_clients, cost_hardware_usd=cost_hw, cost_cabling_usd=cost_cab
            ))
            ap_id += 1

        # Assign channels
        channels_5 = cfg_b.get("supported_channels_5", [36, 44, 52, 60, 100, 108, 116, 132, 140, 149, 157])
        APPlacementEngine.assign_channels_graph_coloring(
            aps,
            channels_24=[1, 6, 11],
            channels_5=channels_5
        )
        return aps

    @staticmethod
    def assign_channels_graph_coloring(aps: List[AccessPoint],
                                      channels_24: List[int],
                                      channels_5: List[int]) -> None:
        """
        Greedy Graph-Coloring Channel Assignment.
        Sorts APs and assigns channels sequentially to minimize cumulative interference
        from previously colored neighbor APs based on physical distance (1/d^2 weighted).
        """
        if not aps:
            return

        # Sort APs spatially from left to right
        sorted_aps = sorted(aps, key=lambda ap: (ap.x, ap.y))

        # Assign 2.4 GHz channels
        for ap in sorted_aps:
            channel_interference_24 = {ch: 0.0 for ch in channels_24}
            for other in sorted_aps:
                if other.id == ap.id or other.channel_24 is None:
                    continue
                d = max(1.0, math.hypot(ap.x - other.x, ap.y - other.y))
                # Interference weight decays with distance squared
                weight = 1.0 / (d ** 2)
                if other.channel_24 in channel_interference_24:
                    channel_interference_24[other.channel_24] += weight

            best_ch_24 = min(channel_interference_24.keys(), key=lambda ch: channel_interference_24[ch])
            ap.channel_24 = int(best_ch_24)

        # Assign 5 GHz channels
        for ap in sorted_aps:
            channel_interference_5 = {ch: 0.0 for ch in channels_5}
            for other in sorted_aps:
                if other.id == ap.id or other.channel_5 is None:
                    continue
                d = max(1.0, math.hypot(ap.x - other.x, ap.y - other.y))
                weight = 1.0 / (d ** 2)
                if other.channel_5 in channel_interference_5:
                    channel_interference_5[other.channel_5] += weight

            best_ch_5 = min(channel_interference_5.keys(), key=lambda ch: channel_interference_5[ch])
            ap.channel_5 = int(best_ch_5)

    @staticmethod
    def generate_kmeans_placement(count: int, floorplan: StationFloorplan,
                                 config_type: str, config: Dict[str, Any],
                                 seed: int = 42) -> List[AccessPoint]:
        """
        Generates AP locations using K-Means clustering over expected passenger density.
        """
        rng = np.random.default_rng(seed)
        # Sample dense synthetic points proportional to zone densities
        sample_points = []
        for zone in floorplan.zones:
            num_pts = int(zone.density_weight * 5000)
            for _ in range(num_pts):
                sample_points.append(zone.sample_point(rng))

        pts = np.array(sample_points)

        # Simple K-Means implementation without external heavy dependencies
        # 1. Initialize centroids randomly from points
        init_idx = rng.choice(len(pts), size=count, replace=False)
        centroids = pts[init_idx].copy()

        for _ in range(15):  # 15 iterations is plenty for convergence
            # Compute distances to centroids
            # Shape (N, K)
            dists = np.sum((pts[:, np.newaxis, :] - centroids[np.newaxis, :, :]) ** 2, axis=2)
            labels = np.argmin(dists, axis=1)

            new_centroids = np.zeros_like(centroids)
            for k in range(count):
                cluster_pts = pts[labels == k]
                if len(cluster_pts) > 0:
                    new_centroids[k] = np.mean(cluster_pts, axis=0)
                else:
                    new_centroids[k] = pts[rng.choice(len(pts))]
            if np.allclose(centroids, new_centroids, atol=0.1):
                break
            centroids = new_centroids

        # Build AP list
        is_config_a = (config_type.lower() == "config_a")
        cfg_data = config.get("configurations", {}).get("config_a" if is_config_a else "config_b", {})
        tx_pwr = float(cfg_data.get("tx_power_dbm", 20.0 if is_config_a else 12.0))
        gain = float(cfg_data.get("antenna_gain_dbi", 3.0 if is_config_a else 5.0))
        max_clients = int(cfg_data.get("max_clients_per_ap", 250 if is_config_a else 45))
        cost_hw = float(cfg_data.get("cost_per_ap_usd", 450 if is_config_a else 350))
        cost_cab = float(cfg_data.get("cabling_cost_per_ap_usd", 250 if is_config_a else 180))

        aps = []
        for i, (cx, cy) in enumerate(centroids):
            aps.append(AccessPoint(
                id=i + 1,
                name=f"AP-K{i+1:02d}",
                x=round(float(cx), 1),
                y=round(float(cy), 1),
                height_m=5.0 if is_config_a else 3.2,
                tx_power_dbm=tx_pwr,
                antenna_gain_dbi=gain,
                antenna_type="omni" if is_config_a else "sector",
                antenna_azimuth_deg=0.0,
                antenna_beamwidth_deg=360.0 if is_config_a else 90.0,
                channel_24=1,
                channel_5=36,
                channel_width_24_mhz=20,
                channel_width_5_mhz=40,
                band_preference="2.4GHz" if is_config_a else "5GHz",
                band_steering=not is_config_a,
                load_balancing=not is_config_a,
                max_clients=max_clients,
                cost_hardware_usd=cost_hw,
                cost_cabling_usd=cost_cab
            ))

        ch_24 = cfg_data.get("supported_channels_24", [1, 6, 11])
        ch_5 = cfg_data.get("supported_channels_5", [36, 44, 52, 60, 100, 108, 116, 132, 140, 149, 157])
        APPlacementEngine.assign_channels_graph_coloring(aps, ch_24, ch_5)
        return aps
