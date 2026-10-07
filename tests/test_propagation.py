"""
tests/test_propagation.py - Unit tests for RF propagation, path loss, RSSI, and SINR models.
"""

import pytest
import yaml
import os
from sim.floorplan import StationFloorplan
from sim.placement import AccessPoint
from sim.propagation import PropagationModel

@pytest.fixture
def sample_config():
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

@pytest.fixture
def floorplan(sample_config):
    return StationFloorplan(sample_config)

@pytest.fixture
def prop_model(sample_config, floorplan):
    return PropagationModel(sample_config, floorplan)

def test_path_loss_increases_with_distance(prop_model):
    """Test that path loss strictly increases as client distance from AP increases."""
    ap = AccessPoint(
        id=1, name="AP1", x=0, y=0, height_m=5.0, tx_power_dbm=20.0,
        antenna_gain_dbi=3.0, antenna_type="omni", antenna_azimuth_deg=0, antenna_beamwidth_deg=360,
        channel_24=1, channel_5=36, channel_width_24_mhz=20, channel_width_5_mhz=40,
        band_preference="2.4GHz", band_steering=False, load_balancing=False, max_clients=100
    )

    pl_10m = prop_model.calculate_path_loss(ap, x=10.0, y=0.0, band="2.4GHz", shadowing_sample=0.0)
    pl_50m = prop_model.calculate_path_loss(ap, x=50.0, y=0.0, band="2.4GHz", shadowing_sample=0.0)
    pl_100m = prop_model.calculate_path_loss(ap, x=100.0, y=0.0, band="2.4GHz", shadowing_sample=0.0)

    assert pl_50m > pl_10m, "Path loss at 50m must be greater than at 10m"
    assert pl_100m > pl_50m, "Path loss at 100m must be greater than at 50m"

def test_frequency_path_loss_difference(prop_model):
    """Test that 5 GHz has higher free-space and log-distance loss than 2.4 GHz at the same distance."""
    ap = AccessPoint(
        id=1, name="AP1", x=0, y=0, height_m=5.0, tx_power_dbm=20.0,
        antenna_gain_dbi=3.0, antenna_type="omni", antenna_azimuth_deg=0, antenna_beamwidth_deg=360,
        channel_24=1, channel_5=36, channel_width_24_mhz=20, channel_width_5_mhz=40,
        band_preference="5GHz", band_steering=False, load_balancing=False, max_clients=100
    )

    pl_24 = prop_model.calculate_path_loss(ap, x=30.0, y=0.0, band="2.4GHz", shadowing_sample=0.0)
    pl_5 = prop_model.calculate_path_loss(ap, x=30.0, y=0.0, band="5GHz", shadowing_sample=0.0)

    assert pl_5 > pl_24, "5 GHz path loss must be higher than 2.4 GHz due to higher frequency attenuation"

def test_obstacle_attenuation(floorplan):
    """Test that intersecting walls/pillars add positive dB attenuation."""
    # Obstacle wall at x=120, y from 0 to 60
    # Segment from (100, 30) to (140, 30) crosses the wall
    loss_crossing = floorplan.calculate_obstacle_attenuation(100, 30, 140, 30)
    # Segment from (50, 30) to (90, 30) does not cross the wall
    loss_open = floorplan.calculate_obstacle_attenuation(50, 30, 90, 30)

    assert loss_crossing >= 8.0, "Ray intersecting wall must suffer at least 8 dB loss"
    assert loss_open < loss_crossing, "Ray with line-of-sight must have lower attenuation than ray through wall"

def test_sinr_drops_with_interferers(prop_model):
    """Test that SINR decreases when co-channel interferers are present."""
    ap1 = AccessPoint(
        id=1, name="AP1", x=20, y=20, height_m=5.0, tx_power_dbm=20.0,
        antenna_gain_dbi=3.0, antenna_type="omni", antenna_azimuth_deg=0, antenna_beamwidth_deg=360,
        channel_24=1, channel_5=36, channel_width_24_mhz=20, channel_width_5_mhz=40,
        band_preference="2.4GHz", band_steering=False, load_balancing=False, max_clients=100
    )
    ap2_interferer = AccessPoint(
        id=2, name="AP2", x=60, y=20, height_m=5.0, tx_power_dbm=20.0,
        antenna_gain_dbi=3.0, antenna_type="omni", antenna_azimuth_deg=0, antenna_beamwidth_deg=360,
        channel_24=1, channel_5=36, channel_width_24_mhz=20, channel_width_5_mhz=40,  # Same channel!
        band_preference="2.4GHz", band_steering=False, load_balancing=False, max_clients=100
    )

    # User at (30, 20)
    _, _, sinr_isolated = prop_model.calculate_sinr(ap1, user_x=30, user_y=20, band="2.4GHz", all_aps=[ap1])
    _, _, sinr_with_interferer = prop_model.calculate_sinr(ap1, user_x=30, user_y=20, band="2.4GHz", all_aps=[ap1, ap2_interferer])

    assert sinr_isolated > sinr_with_interferer, "SINR must decrease when a co-channel AP is active nearby"
