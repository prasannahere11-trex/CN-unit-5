"""
sim/propagation.py - High-Performance Propagation, RSSI, and SINR Engine.
"""

import math
import numpy as np
from typing import List, Dict, Tuple, Optional, Any
from .floorplan import StationFloorplan, User
from .placement import AccessPoint


class PropagationModel:
    """Calculates RF path loss, RSSI, interference, and SINR."""

    def __init__(self, config: Dict[str, Any], floorplan: StationFloorplan):
        self.config = config
        self.floorplan = floorplan
        prop_cfg = config.get("propagation", {})
        self.d0 = float(prop_cfg.get("d0", 1.0))
        self.n_24 = float(prop_cfg.get("path_loss_exp_24", 3.0))
        self.n_5 = float(prop_cfg.get("path_loss_exp_5", 3.3))
        self.sigma = float(prop_cfg.get("shadowing_sigma_db", 6.5))
        self.body_loss = float(prop_cfg.get("body_loss_db_per_density", 4.0))
        self.noise_24_dbm = float(prop_cfg.get("noise_floor_24_dbm", -95.0))
        self.noise_5_dbm = float(prop_cfg.get("noise_floor_5_dbm", -92.0))
        self.acr_db = float(prop_cfg.get("adjacent_channel_rejection_db", 25.0))
        self.alpha_adj = 10.0 ** (-self.acr_db / 10.0)

        self.pl0_24 = 20.0 * math.log10(2412.0) - 27.55
        self.pl0_5 = 20.0 * math.log10(5200.0) - 27.55

    def compute_distance_3d(self, ap: AccessPoint, x: float, y: float, user_height_m: float = 1.2) -> float:
        dx = ap.x - x
        dy = ap.y - y
        dz = ap.height_m - user_height_m
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)
        return max(dist, self.d0)

    def calculate_path_loss(self, ap: AccessPoint, x: float, y: float,
                            band: str, crowd_density_factor: float = 0.5,
                            shadowing_sample: Optional[float] = None) -> float:
        dist_3d = self.compute_distance_3d(ap, x, y)
        is_5ghz = (band == "5GHz")
        pl0 = self.pl0_5 if is_5ghz else self.pl0_24
        n_exp = self.n_5 if is_5ghz else self.n_24

        pl_dist = pl0 + 10.0 * n_exp * math.log10(dist_3d / self.d0)
        shadowing = shadowing_sample if shadowing_sample is not None else 0.0
        obstacle_loss = self.floorplan.calculate_obstacle_attenuation(ap.x, ap.y, x, y)
        band_multiplier = 1.2 if is_5ghz else 1.0
        crowd_loss = crowd_density_factor * self.body_loss * band_multiplier

        return float(pl_dist + shadowing + obstacle_loss + crowd_loss)

    def calculate_rssi(self, ap: AccessPoint, x: float, y: float,
                       band: str, crowd_density_factor: float = 0.5,
                       shadowing_sample: Optional[float] = None) -> float:
        path_loss = self.calculate_path_loss(ap, x, y, band, crowd_density_factor, shadowing_sample)
        gain = ap.get_effective_gain(x, y)
        rssi = ap.tx_power_dbm + gain - path_loss
        return round(float(rssi), 2)

    def calculate_sinr(self, serving_ap: AccessPoint, user_x: float, user_y: float,
                       band: str, all_aps: List[AccessPoint],
                       crowd_density: float = 0.5,
                       rng: Optional[np.random.Generator] = None) -> Tuple[float, float, float]:
        s_serving = rng.normal(0, self.sigma) if rng is not None else 0.0
        serving_rssi = self.calculate_rssi(serving_ap, user_x, user_y, band, crowd_density, s_serving)
        serving_power_mw = 10.0 ** (serving_rssi / 10.0)

        noise_dbm = self.noise_5_dbm if band == "5GHz" else self.noise_24_dbm
        noise_mw = 10.0 ** (noise_dbm / 10.0)

        serving_ch = serving_ap.channel_5 if band == "5GHz" else serving_ap.channel_24

        interference_mw = 0.0
        for ap in all_aps:
            if ap.id == serving_ap.id:
                continue

            ap_ch = ap.channel_5 if band == "5GHz" else ap.channel_24
            if ap_ch is None:
                continue

            # Fast distance check: if AP is further than 100m, interference power is < 1e-10 mW
            d = math.hypot(ap.x - user_x, ap.y - user_y)
            if d > 100.0:
                continue

            is_co_channel = (ap_ch == serving_ch)
            is_adj_channel = False

            if band == "2.4GHz":
                diff = abs(ap_ch - serving_ch)
                if 0 < diff < 5:
                    is_adj_channel = True
            else:
                diff = abs(ap_ch - serving_ch)
                if diff == 4 or diff == 8:
                    is_adj_channel = True

            if not is_co_channel and not is_adj_channel:
                continue

            s_int = rng.normal(0, self.sigma) if rng is not None else 0.0
            int_rssi = self.calculate_rssi(ap, user_x, user_y, band, crowd_density, s_int)
            int_mw = 10.0 ** (int_rssi / 10.0)

            if is_co_channel:
                interference_mw += int_mw
            elif is_adj_channel:
                interference_mw += int_mw * self.alpha_adj

        total_noise_plus_int_mw = noise_mw + interference_mw
        sinr_ratio = max(1e-4, serving_power_mw / total_noise_plus_int_mw)
        sinr_db = 10.0 * math.log10(sinr_ratio)
        int_dbm = 10.0 * math.log10(max(1e-12, interference_mw))

        return (serving_rssi, round(int_dbm, 2), round(sinr_db, 2))

    def generate_heatmap_grid(self, aps: List[AccessPoint],
                              grid_step: float = 3.5,
                              preferred_band: Optional[str] = None) -> Dict[str, Any]:
        x_min, x_max = 0.0, self.floorplan.width
        y_min, y_max = -55.0, self.floorplan.height

        x_coords = np.arange(x_min, x_max + grid_step, grid_step).tolist()
        y_coords = np.arange(y_min, y_max + grid_step, grid_step).tolist()

        rssi_matrix = []
        sinr_matrix = []
        best_ap_matrix = []

        for y in y_coords:
            rssi_row = []
            sinr_row = []
            ap_row = []
            for x in x_coords:
                best_rssi = -120.0
                best_ap = None
                best_band = "5GHz"

                for ap in aps:
                    band = preferred_band or ap.band_preference
                    rssi = self.calculate_rssi(ap, x, y, band, crowd_density_factor=0.3, shadowing_sample=0.0)
                    if rssi > best_rssi:
                        best_rssi = rssi
                        best_ap = ap
                        best_band = band

                if best_ap is not None:
                    _, _, sinr = self.calculate_sinr(best_ap, x, y, best_band, aps, crowd_density=0.3, rng=None)
                    rssi_row.append(round(best_rssi, 1))
                    sinr_row.append(round(sinr, 1))
                    ap_row.append(best_ap.id)
                else:
                    rssi_row.append(-120.0)
                    sinr_row.append(-10.0)
                    ap_row.append(0)

            rssi_matrix.append(rssi_row)
            sinr_matrix.append(sinr_row)
            best_ap_matrix.append(ap_row)

        return {
            "x_coords": [round(float(x), 1) for x in x_coords],
            "y_coords": [round(float(y), 1) for y in y_coords],
            "grid_step": grid_step,
            "rssi_matrix": rssi_matrix,
            "sinr_matrix": sinr_matrix,
            "best_ap_matrix": best_ap_matrix,
            "bounds": {"x_min": x_min, "x_max": x_max, "y_min": y_min, "y_max": y_max}
        }
