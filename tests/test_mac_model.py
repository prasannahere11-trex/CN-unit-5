"""
tests/test_mac_model.py - Unit tests for MCS mapping, CSMA/CA airtime contention, and fairness.
"""

import pytest
import yaml
import os
from sim.floorplan import StationFloorplan, User
from sim.placement import AccessPoint
from sim.propagation import PropagationModel
from sim.mac_model import MACModel
from sim.metrics import MetricsEngine

@pytest.fixture
def sample_config():
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

@pytest.fixture
def mac_engine(sample_config):
    floorplan = StationFloorplan(sample_config)
    prop = PropagationModel(sample_config, floorplan)
    return MACModel(sample_config, prop)

def test_mcs_sinr_mapping(mac_engine):
    """Test that higher SINR yields higher MCS rate and lower packet error rate."""
    mcs_low, rate_low, per_low = mac_engine.sinr_to_phy_rate(sinr_db=5.0, channel_width_mhz=20)
    mcs_high, rate_high, per_high = mac_engine.sinr_to_phy_rate(sinr_db=26.0, channel_width_mhz=20)

    assert mcs_high > mcs_low, "Higher SINR must map to higher MCS index"
    assert rate_high > rate_low, "Higher SINR must provide higher PHY rate"
    assert per_high <= per_low, "Higher SINR must yield equal or lower base PER"

def test_throughput_drops_with_contending_clients(mac_engine):
    """Test that per-client throughput decreases as client count per AP increases."""
    ap = AccessPoint(
        id=1, name="AP1", x=20, y=20, height_m=5.0, tx_power_dbm=20.0,
        antenna_gain_dbi=3.0, antenna_type="omni", antenna_azimuth_deg=0, antenna_beamwidth_deg=360,
        channel_24=1, channel_5=36, channel_width_24_mhz=20, channel_width_5_mhz=40,
        band_preference="2.4GHz", band_steering=False, load_balancing=False, max_clients=250
    )

    # 1. Test with 5 users
    users_5 = [
        User(id=i, x=22, y=20, zone_id="concourse", device_type="dual_band", traffic_type="video",
             demand_mbps=3.0, packet_size_bytes=1400, latency_tolerance_ms=100, connected_ap_id=1,
             connected_band="2.4GHz", phy_rate_mbps=50.0, sinr_db=20.0)
        for i in range(5)
    ]
    mac_engine.simulate_mac_throughput(users_5, [ap])
    avg_tput_5 = sum(u.throughput_mbps for u in users_5) / 5.0

    # 2. Test with 50 users on the same AP
    users_50 = [
        User(id=i, x=22, y=20, zone_id="concourse", device_type="dual_band", traffic_type="video",
             demand_mbps=3.0, packet_size_bytes=1400, latency_tolerance_ms=100, connected_ap_id=1,
             connected_band="2.4GHz", phy_rate_mbps=50.0, sinr_db=20.0)
        for i in range(50)
    ]
    mac_engine.simulate_mac_throughput(users_50, [ap])
    avg_tput_50 = sum(u.throughput_mbps for u in users_50) / 50.0

    assert avg_tput_50 < avg_tput_5, "Per-client throughput must degrade under heavy CSMA/CA contention"

def test_jains_fairness_bounds():
    """Test that Jain's fairness index is always in [0.0, 1.0]."""
    # Identical values -> perfectly fair (1.0)
    assert MetricsEngine.calculate_jains_fairness([10.0, 10.0, 10.0, 10.0]) == 1.0
    # Unequal values
    fairness = MetricsEngine.calculate_jains_fairness([100.0, 1.0, 0.5, 0.1])
    assert 0.0 <= fairness <= 1.0, "Jain's fairness index must always be between 0 and 1"
    # Zero values
    assert 0.0 <= MetricsEngine.calculate_jains_fairness([0.0, 0.0]) <= 1.0
