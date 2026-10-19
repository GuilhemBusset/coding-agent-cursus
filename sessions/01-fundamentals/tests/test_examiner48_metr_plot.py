"""Independently check the METR plot against the cited primary measurements.

Snapshot read 2026-10-19 from https://metr.org/assets/benchmark_results_1_1.yaml:
all is_sota releases from 2023 onward; horizons and intervals are in minutes.
No network is required to rerun this dated chart check.
"""
from datetime import date
from pathlib import Path
import math
import re
import xml.etree.ElementTree as ET


MEASUREMENTS = [
    ('2023-03-14', 3.987428, 1.93292, 7.995283),
    ('2023-11-06', 4.044959, 1.866859, 8.443226),
    ('2024-05-13', 6.991195, 4.001482, 12.905741),
    ('2024-06-20', 11.395377, 5.489734, 22.384214),
    ('2024-09-12', 20.326586, 11.716193, 33.379877),
    ('2024-10-22', 20.522872, 10.144026, 40.82028),
    ('2024-12-05', 38.831588, 21.164512, 64.95249),
    ('2025-02-24', 60.388937, 33.006168, 104.226017),
    ('2025-04-16', 119.732634, 74.615398, 190.943818),
    ('2025-08-07', 203.012577, 112.641357, 405.551565),
    ('2025-11-18', 224.325884, 139.565157, 379.235434),
    ('2025-11-24', 292.994594, 161.717714, 623.704698),
    ('2025-12-11', 352.249302, 198.067494, 815.177445),
    ('2026-02-05', 718.80683, 316.685725, 3633.786163),
    ('2026-04-07', 1044.780145, 508.876789, 3304.261235),
]


def test_metr_frontier_points_and_intervals_use_the_published_scale():
    deck = (Path(__file__).resolve().parents[1] / 'cursus/03-agent.html').read_text()
    section = re.search(r'<section\b[^>]*\bid="time-horizons".*?</section>', deck, re.S).group()
    svg = ET.fromstring(re.search(r'<svg\b.*?</svg>', section, re.S).group())
    points = [e for e in svg.iter('circle') if e.get('class') == 'pt']
    intervals = [e for e in svg.iter('line') if e.get('class') == 'ci']
    assert len(points) == len(intervals) == len(MEASUREMENTS)
    by_date = {}
    for point, interval in zip(points, intervals):
        title = point.find('title').text
        release = re.search(r'\d{4}-\d{2}-\d{2}', title).group()
        assert release not in by_date
        by_date[release] = (point, interval, title)
    origin, end = date(2023, 1, 1), date(2026, 7, 1)
    def y(minutes):
        raw = 192 - 180 * math.log(minutes / 2) / math.log(2400 / 2)
        return max(12, min(192, raw))
    for release, estimate, low, high in MEASUREMENTS:
        point, interval, title = by_date[release]
        x = 60 + 564 * (date.fromisoformat(release) - origin).days / (end - origin).days
        assert abs(float(point.get('cx')) - x) <= .1, title
        assert abs(float(point.get('cy')) - y(estimate)) <= .1, title
        assert abs(float(interval.get('x1')) - x) <= .1, title
        assert abs(float(interval.get('x2')) - x) <= .1, title
        assert abs(float(interval.get('y1')) - y(low)) <= .1, title
        assert abs(float(interval.get('y2')) - y(high)) <= .1, title
        assert f': {round(estimate)} min' in title
