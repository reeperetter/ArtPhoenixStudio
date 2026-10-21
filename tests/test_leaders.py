import math

import numpy as np

from paint_by_numbers.geometry.labels import NumberSpot
from paint_by_numbers.geometry.leaders import place_leaders
from paint_by_numbers.geometry.planar import Chain


def _square(x0, y0, x1, y1):
    pts = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]], float)
    return Chain(pts, True, (0, 1), 1.0, pts, False)


def test_leader_placed_outside_tiny_region():
    chains = [_square(100, 100, 104, 104)]                 # крихітна ділянка 4x4 px
    spots = [NumberSpot(0, 7, 102, 102, 0.5, 0.0), NumberSpot(1, 3, 20, 20, 15, 8.0)]
    r = place_leaders(spots, chains, (200, 200), 7.0, 1.0, 3.0)
    s = spots[0]
    assert r["placed"] == 1 and not r["failed"]
    assert s.anchor == (102, 102) and s.digit_px == 7.0
    assert math.hypot(s.x - 102, s.y - 102) > 4              # номер поза ділянкою
    assert math.hypot(s.x - 20, s.y - 20) > 8                # і не на чужому номері
    assert spots[1].anchor is None


def test_leader_fails_when_no_room():
    chains = [_square(1, 1, 3, 3)]
    spots = [NumberSpot(0, 7, 2, 2, 0.2, 0.0)]
    r = place_leaders(spots, chains, (6, 6), 7.0, 1.0, 3.0)
    assert r["failed"] == [0] and spots[0].digit_px == 0
