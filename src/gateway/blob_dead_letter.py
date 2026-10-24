"""Persist rejected match events in Azure Blob Storage."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from azure.storage.blob import ContentSettings
from azure.storage.blob.aio import BlobServiceClient


class BlobDeadLetterSink:
    def __init__(self, account_url: str, container_name: str, credential) -> None:
        self.client = BlobServiceClient(account_url=account_url, credential=credential)
        self.container = self.client.get_container_client(container_name)

    async def write(self, event: Any, reason: str, attempts: int) -> None:
        when = datetime.now(timezone.utc)
        name = f"{when:%Y/%m/%d/%H%M%S}-{uuid.uuid4()}.json"
        record = {
            "failed_at": when.isoformat(), "reason": reason,
            "attempts": attempts, "event": event,
        }
        await self.container.upload_blob(
            name=name, data=json.dumps(record, separators=(",", ":")),
            overwrite=False, content_settings=ContentSettings(content_type="application/json"),
        )

    async def close(self) -> None:
        await self.client.close()
