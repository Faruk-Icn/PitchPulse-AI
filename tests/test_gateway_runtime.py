"""Check the actual ASGI server can negotiate a browser WebSocket."""

import asyncio
import socket
import subprocess
import sys
import unittest

from websockets.asyncio.client import connect


class GatewayRuntimeTests(unittest.TestCase):
    def test_uvicorn_studio_websocket_handshake(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "src.gateway.app:app",
             "--host", "127.0.0.1", "--port", str(port), "--log-level", "error"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

        async def handshake():
            for _ in range(40):
                if server.poll() is not None:
                    self.fail("gateway server exited before WebSocket handshake")
                try:
                    async with connect(f"ws://127.0.0.1:{port}/ws/studio", open_timeout=1) as websocket:
                        self.assertEqual(websocket.state.name, "OPEN")
                        return
                except (OSError, TimeoutError):
                    await asyncio.sleep(0.1)
            self.fail("gateway did not accept a WebSocket connection")

        try:
            asyncio.run(handshake())
        finally:
            server.terminate()
            server.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
