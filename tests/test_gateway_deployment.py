"""Deployment mode and durable stream handling."""

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from src.gateway.app import create_app
from src.gateway.blob_dead_letter import BlobDeadLetterSink
from src.gateway.engine import receive_event_hubs


class DeploymentRuntimeTests(unittest.TestCase):
    def test_services_expose_only_their_own_page(self):
        for mode, available, unavailable in (
            ("broadcast", "/studio", "/fan"),
            ("fan", "/fan", "/studio"),
        ):
            with self.subTest(mode=mode), patch.dict("os.environ", {"PITCHPULSE_MODE": mode}):
                with TestClient(create_app()) as client:
                    self.assertEqual(client.get(available).status_code, 200)
                    self.assertEqual(client.get(unavailable).status_code, 404)

    def test_blob_sink_persists_event_and_failure_metadata(self):
        with patch("src.gateway.blob_dead_letter.BlobServiceClient") as service:
            container = service.return_value.get_container_client.return_value
            container.upload_blob = AsyncMock()
            sink = BlobDeadLetterSink("https://storage.invalid", "dead-letter", object())
            asyncio.run(sink.write({"event_id": "e-1"}, "invalid", 2))
        payload = json.loads(container.upload_blob.call_args.kwargs["data"])
        self.assertEqual(payload["event"], {"event_id": "e-1"})
        self.assertEqual(payload["reason"], "invalid")
        self.assertEqual(payload["attempts"], 2)

    def test_checkpoint_advances_after_processing(self):
        order = []
        event = SimpleNamespace(body_as_str=lambda: '{"event_id":"e-1"}')
        partition = SimpleNamespace(
            partition_id="0",
            update_checkpoint=AsyncMock(side_effect=lambda _event: order.append("checkpoint")),
        )
        engine = SimpleNamespace(
            processor=SimpleNamespace(dead_letter=None),
            handle_body=AsyncMock(side_effect=lambda _body: order.append("process")),
            drain=AsyncMock(),
        )
        consumer = MagicMock()
        consumer.__aenter__ = AsyncMock(return_value=consumer)
        consumer.__aexit__ = AsyncMock(return_value=None)

        async def receive(*, on_event, **_kwargs):
            await on_event(partition, event)
            self.assertEqual(order, ["process"])
            await on_event(partition, None)
            for _ in range(19):
                await on_event(partition, event)
            self.assertEqual(partition.update_checkpoint.await_count, 1)
            await on_event(partition, event)
            self.assertEqual(partition.update_checkpoint.await_count, 2)

        consumer.receive = receive
        credential = MagicMock()
        credential.__aenter__ = AsyncMock(return_value=credential)
        credential.__aexit__ = AsyncMock(return_value=None)
        checkpoint = MagicMock()
        checkpoint.close = AsyncMock()
        dead_letter = MagicMock()
        dead_letter.close = AsyncMock()
        env = {
            "EVENT_HUB_LISTEN_CONNECTION_STRING": "Endpoint=sb://test.invalid/;SharedAccessKeyName=listen;SharedAccessKey=x",
            "EVENT_HUB_NAME": "match-events",
            "BLOB_ACCOUNT_URL": "https://storage.invalid",
            "CHECKPOINT_CONTAINER": "checkpoints",
            "DEAD_LETTER_CONTAINER": "dead-letter",
        }
        with patch.dict("os.environ", env), \
                patch("src.gateway.engine.DefaultAzureCredential", return_value=credential), \
                patch("src.gateway.engine.BlobCheckpointStore", return_value=checkpoint), \
                patch("src.gateway.engine.BlobDeadLetterSink", return_value=dead_letter), \
                patch("src.gateway.engine.EventHubConsumerClient.from_connection_string", return_value=consumer):
            asyncio.run(receive_event_hubs(engine))
        self.assertEqual(order, ["process", "checkpoint"] + ["process"] * 20 + ["checkpoint"])
        self.assertIs(engine.processor.dead_letter, dead_letter)
        dead_letter.close.assert_awaited_once()
        checkpoint.close.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
