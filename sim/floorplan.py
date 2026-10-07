"""
sim/floorplan.py - Floorplan, Zones, Obstacles, and Passenger Distribution.
"""

import math
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any


@dataclass
class Zone:
    """Represents a physical zone inside the railway station."""
    id: str
    name: str
    x: float
    y: float
    width: float
    height: float
    density_weight: float
    color: str

    def contains(self, px: float, py: float) -> bool:
        return (self.x <= px <= self.x + self.width) and (self.y <= py <= self.y + self.height)

    def sample_point(self, rng: np.random.Generator) -> Tuple[float, float]:
        px = rng.uniform(self.x, self.x + self.width)
        py = rng.uniform(self.y, self.y + self.height)
        return float(px), float(py)


@dataclass
class Obstacle:
    """Represents a wall or pillar causing RF attenuation."""
    obstacle_type: str  # "wall" or "pillar"
    name: str = ""
    x1: float = 0.0
    y1: float = 0.0
    x2: float = 0.0
    y2: float = 0.0
    x: float = 0.0
    y: float = 0.0
    radius: float = 1.0
    attenuation_db: float = 8.0
    min_x: float = 0.0
    max_x: float = 0.0
    min_y: float = 0.0
    max_y: float = 0.0

    def __post_init__(self):
        if self.obstacle_type == "wall":
            self.min_x = min(self.x1, self.x2)
            self.max_x = max(self.x1, self.x2)
            self.min_y = min(self.y1, self.y2)
            self.max_y = max(self.y1, self.y2)
        else:
            self.min_x = self.x - self.radius
            self.max_x = self.x + self.radius
            self.min_y = self.y - self.radius
            self.max_y = self.y + self.radius


@dataclass
class User:
    """Represents a connected passenger device."""
    id: int
    x: float
    y: float
    zone_id: str
    device_type: str        # 'dual_band', '5ghz_only', '2.4ghz_only'
    traffic_type: str       # 'video_streaming', 'web_browsing', 'voip_call', 'messaging_idle'
    demand_mbps: float
    packet_size_bytes: int
    latency_tolerance_ms: float
    connected_ap_id: Optional[int] = None
    connected_band: Optional[str] = None  # '2.4GHz' or '5GHz'
    channel: Optional[int] = None
    rssi_dbm: float = -100.0
    sinr_db: float = 0.0
    phy_rate_mbps: float = 0.0
    throughput_mbps: float = 0.0
    latency_ms: float = 0.0
    packet_loss_pct: float = 0.0
    retransmissions: int = 0


class StationFloorplan:
    """Railway Station Environment Model."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        station_cfg = config.get("station", {})
        self.width = float(station_cfg.get("width", 200.0))
        self.height = float(station_cfg.get("height", 60.0))
        self.backhaul_gbps = float(station_cfg.get("backhaul_gbps", 2.0))

        # Load Zones
        self.zones: List[Zone] = []
        for z in config.get("zones", []):
            self.zones.append(Zone(
                id=z["id"],
                name=z["name"],
                x=float(z["x"]),
                y=float(z["y"]),
                width=float(z["width"]),
                height=float(z["height"]),
                density_weight=float(z["density_weight"]),
                color=z.get("color", "#3b82f6")
            ))

        # Load Obstacles
        self.obstacles: List[Obstacle] = []
        for obs in config.get("obstacles", []):
            obs_type = obs.get("type", "wall")
            if obs_type == "wall":
                self.obstacles.append(Obstacle(
                    obstacle_type="wall",
                    name=obs.get("name", "Wall"),
                    x1=float(obs["x1"]),
                    y1=float(obs["y1"]),
                    x2=float(obs["x2"]),
                    y2=float(obs["y2"]),
                    attenuation_db=float(obs.get("attenuation_db", 8.0))
                ))
            elif obs_type == "pillar":
                self.obstacles.append(Obstacle(
                    obstacle_type="pillar",
                    name="Pillar",
                    x=float(obs["x"]),
                    y=float(obs["y"]),
                    radius=float(obs.get("radius", 1.5)),
                    attenuation_db=float(obs.get("attenuation_db", 6.0))
                ))

    @staticmethod
    def _segments_intersect(p1: Tuple[float, float], p2: Tuple[float, float],
                            q1: Tuple[float, float], q2: Tuple[float, float]) -> bool:
        """Fast 2D segment intersection."""
        def ccw(A, B, C):
            return (C[1] - A[1]) * (B[0] - A[0]) > (B[1] - A[1]) * (C[0] - A[0])

        return (ccw(p1, q1, q2) != ccw(p2, q1, q2)) and (ccw(p1, p2, q1) != ccw(p1, p2, q2))

    @staticmethod
    def _segment_intersects_circle(p1: Tuple[float, float], p2: Tuple[float, float],
                                  cx: float, cy: float, radius: float) -> bool:
        x1, y1 = p1
        x2, y2 = p2
        dx = x2 - x1
        dy = y2 - y1
        l2 = dx * dx + dy * dy
        if l2 == 0:
            return math.hypot(x1 - cx, y1 - cy) <= radius
        t = max(0.0, min(1.0, ((cx - x1) * dx + (cy - y1) * dy) / l2))
        proj_x = x1 + t * dx
        proj_y = y1 + t * dy
        return ((cx - proj_x) ** 2 + (cy - proj_y) ** 2) <= (radius * radius)

    def calculate_obstacle_attenuation(self, ap_x: float, ap_y: float, user_x: float, user_y: float) -> float:
        """Calculates total dB attenuation caused by line-of-sight intersecting walls and pillars with bounding box culling."""
        seg_min_x = min(ap_x, user_x)
        seg_max_x = max(ap_x, user_x)
        seg_min_y = min(ap_y, user_y)
        seg_max_y = max(ap_y, user_y)

        total_loss_db = 0.0
        p1 = (ap_x, ap_y)
        p2 = (user_x, user_y)

        for obs in self.obstacles:
            # Fast Bounding Box Reject
            if seg_max_x < obs.min_x or seg_min_x > obs.max_x or seg_max_y < obs.min_y or seg_min_y > obs.max_y:
                continue

            if obs.obstacle_type == "wall":
                if self._segments_intersect(p1, p2, (obs.x1, obs.y1), (obs.x2, obs.y2)):
                    total_loss_db += obs.attenuation_db
            elif obs.obstacle_type == "pillar":
                if self._segment_intersects_circle(p1, p2, obs.x, obs.y, obs.radius):
                    total_loss_db += obs.attenuation_db

        return total_loss_db

    def generate_passengers(self, scenario_key: str = "normal",
                            custom_user_count: Optional[int] = None,
                            seed: Optional[int] = None) -> List[User]:
        rng = np.random.default_rng(seed)
        passengers_cfg = self.config.get("passengers", {})
        scenarios_cfg = passengers_cfg.get("scenarios", {})
        scenario = scenarios_cfg.get(scenario_key, scenarios_cfg.get("normal", {}))

        total_users = custom_user_count if custom_user_count is not None else scenario.get("users", 800)
        burst_platform = scenario.get("burst_platform", None)
        burst_multiplier = float(scenario.get("burst_multiplier", 1.0))

        zone_weights = {}
        for z in self.zones:
            weight = z.density_weight
            if burst_platform and z.id == burst_platform:
                weight *= burst_multiplier
            zone_weights[z.id] = weight

        total_weight = sum(zone_weights.values())
        norm_weights = [zone_weights[z.id] / total_weight for z in self.zones]

        dev_mix = passengers_cfg.get("device_mix", {})
        dual_ratio = float(dev_mix.get("dual_band_ratio", 0.70))
        five_ratio = float(dev_mix.get("five_ghz_only_ratio", 0.20))
        legacy_ratio = float(dev_mix.get("legacy_24_only_ratio", 0.10))
        dev_types = ["dual_band", "5ghz_only", "2.4ghz_only"]
        dev_probs = [dual_ratio, five_ratio, legacy_ratio]
        s_dev = sum(dev_probs)
        dev_probs = [p / s_dev for p in dev_probs]

        traffic_cfg = passengers_cfg.get("traffic", {})
        profiles = traffic_cfg.get("profiles", {})
        profile_names = list(profiles.keys())
        profile_shares = [profiles[k]["share"] for k in profile_names]
        s_prof = sum(profile_shares)
        profile_shares = [p / s_prof for p in profile_shares]

        users: List[User] = []
        for uid in range(total_users):
            chosen_zone: Zone = rng.choice(self.zones, p=norm_weights)
            ux, uy = chosen_zone.sample_point(rng)
            dev_type = str(rng.choice(dev_types, p=dev_probs))
            prof_name = str(rng.choice(profile_names, p=profile_shares))
            prof_info = profiles[prof_name]
            base_rate = float(prof_info["rate_mbps"])
            rate_variation = rng.uniform(0.75, 1.25)
            actual_demand = max(0.02, base_rate * rate_variation)

            users.append(User(
                id=uid,
                x=ux,
                y=uy,
                zone_id=chosen_zone.id,
                device_type=dev_type,
                traffic_type=prof_name,
                demand_mbps=round(actual_demand, 3),
                packet_size_bytes=int(prof_info.get("packet_size_bytes", 1400)),
                latency_tolerance_ms=float(prof_info.get("latency_tolerance_ms", 100.0))
            ))

        return users
