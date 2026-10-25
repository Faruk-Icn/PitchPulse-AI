"""Load-test accounting and staging URL contract."""

import asyncio
import unittest

from scripts.benchmark_stream import benchmark, percentile
from scripts.verify_staging import socket_url


class BenchmarkTests(unittest.TestCase):
    def test_fanout_delivers_every_event_under_concurrent_load(self):
        result = asyncio.run(benchmark(events=30, studio_clients=8, fan_clients=24))
        # The generator sends 22 roster records before the 30 measured plays.
        self.assertEqual(result["socket_messages"], (22 + 30) * (8 + 24))
        self.assertLess(result["p95_ms"], 1000)
        self.assertGreater(result["events_per_second"], 0)

    def test_nearest_rank_percentile_and_staging_websocket_urls(self):
        self.assertEqual(percentile(list(range(10)), .95), 9)
        self.assertEqual(socket_url("https://example.test/studio", "/ws/studio"), "wss://example.test/ws/studio")
        with self.assertRaises(ValueError):
            socket_url("not-a-site", "/ws/studio")


if __name__ == "__main__":
    unittest.main()
