"""Fan-out reuses encoded payloads without changing delivery."""

import asyncio
import json
import unittest
from unittest.mock import patch

from src.agents.crew import MatchAgentCrew
from src.gateway.fans import FanHub, FanSubscription
from src.gateway.overlays import OverlayHub, StudioSubscription
from src.gateway.personalization import FanProfile


PASS = {
    "schema_version": "1.0", "event_id": "6e93cb84-f6e1-4990-a42e-13d066bf0869",
    "match_id": "match-1", "sequence": 0,
    "occurred_at": "2026-01-01T00:00:00Z", "event_type": "pass",
    "player_id": "home-07", "recipient_id": "home-09", "team_id": "HOME",
    "start": {"x": 30, "y": 50}, "end": {"x": 60, "y": 50},
    "outcome": "completed",
}


class Socket:
    def __init__(self):
        self.messages = []

    async def send_text(self, payload):
        self.messages.append(payload)


class FanoutTests(unittest.TestCase):
    def test_fans_share_one_localization_and_encoding_per_language(self):
        async def run():
            result = await MatchAgentCrew("match-1").process(PASS)
            hub = FanHub()
            sockets = [Socket() for _ in range(3)]
            for socket, language in zip(sockets, ("en", "en", "es")):
                hub._clients[socket] = FanSubscription(
                    "match-1", FanProfile(language, "concise"), False, asyncio.Lock(),
                )
            original = hub._localized_record
            with patch.object(hub, "_localized_record", wraps=original) as localize:
                await hub.broadcast(PASS, result)
            self.assertEqual(localize.call_count, 2)
            self.assertIs(sockets[0].messages[0], sockets[1].messages[0])
            self.assertEqual(json.loads(sockets[2].messages[0])["language"], "es")

        asyncio.run(run())

    def test_studio_encodes_once_for_all_matching_sockets(self):
        async def run():
            hub = OverlayHub()
            first, second, other = Socket(), Socket(), Socket()
            for socket, match_id in ((first, None), (second, "match-1"), (other, "match-2")):
                hub._clients[socket] = StudioSubscription(match_id, asyncio.Lock())
            await hub.broadcast({"kind": "analysis", "match_id": "match-1", "sequence": 0})
            self.assertEqual(len(first.messages), 1)
            self.assertIs(first.messages[0], second.messages[0])
            self.assertEqual(other.messages, [])

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
