"""Drive the real Uvicorn parsers and Market app without making network calls."""

import asyncio
import json
import unittest
from unittest.mock import Mock, patch

import uvicorn
from fastapi import HTTPException
from uvicorn.server import ServerState

from app.main import app
from app.market_data import get_market_service


class SearchAccessTests(unittest.IsolatedAsyncioTestCase):
    async def request(self, protocol, target, *, limit=None):
        config = uvicorn.Config(app, http=protocol, log_config=None, limit_concurrency=limit)
        config.load()
        state = ServerState()
        connection = config.http_protocol_class(config, server_state=state, app_state={})
        transport = Mock(spec=asyncio.Transport)
        transport.get_extra_info.return_value = None
        transport.is_closing.return_value = False
        connection.connection_made(transport)
        try:
            connection.data_received(
                f"GET {target} HTTP/1.1\r\nHost: fixture.invalid\r\n"
                "X-Request-Id: caller-private\r\nCookie: fixture=private\r\n\r\n".encode()
            )
            await asyncio.gather(*state.tasks)
            return b"".join(call.args[0] for call in transport.write.call_args_list)
        finally:
            connection.connection_lost(None)

    async def test_search_logs_and_ordinary_requests_on_both_protocols(self):
        service = Mock()
        service.search.return_value = {"stocks": []}
        with patch.dict(app.dependency_overrides, {get_market_service: lambda: service}):
            for protocol in ("h11", "httptools"):
                with self.subTest(protocol=protocol):
                    ids = []
                    with (
                        self.assertLogs("market.search.access") as private,
                        self.assertLogs("uvicorn.access") as ordinary,
                    ):
                        for target, status in [
                            ("/api/stocks/search?q=private+query", 200),
                            ("/api/stocks/search?q=", 422),
                            ("/api/stocks/search/?q=private+query", 307),
                        ]:
                            reply = await self.request(protocol, target)
                            self.assertIn(f"HTTP/1.1 {status}".encode(), reply)
                            if status == 200:
                                self.assertIn(b'{"stocks":[]}', reply)
                            event = json.loads(private.records[-1].getMessage())
                            self.assertEqual(
                                set(event),
                                {"event", "route", "status", "request_id", "duration_ms"},
                            )
                            self.assertEqual(
                                (event["route"], event["status"]), ("stock_search", status)
                            )
                            self.assertGreaterEqual(event["duration_ms"], 0)
                            self.assertRegex(event["request_id"], "^[0-9a-f]{32}$")
                            self.assertIn(
                                b"x-request-id: " + event["request_id"].encode(), reply.lower()
                            )
                            ids.append(event["request_id"])
                        await self.request(protocol, "/health?control=public")
                    self.assertEqual(len(set(ids)), 3)
                    self.assertEqual(len(private.records), 3)
                    self.assertEqual(len(ordinary.records), 1)
                    self.assertIn("/health?control=public", ordinary.records[0].getMessage())
                    self.assertNotIn("private", "\n".join(private.output + ordinary.output))
                    service.search.assert_called_with("private query")

    async def test_error_and_server_admission_status_remain_visible(self):
        service = Mock()
        service.search.side_effect = HTTPException(429)
        with (
            patch.dict(app.dependency_overrides, {get_market_service: lambda: service}),
            self.assertLogs("market.search.access") as private,
            self.assertNoLogs("uvicorn.access"),
        ):
            await self.request("h11", "/api/stocks/search?q=private")
            await self.request("h11", "/api/stocks/search?q=private", limit=1)
        limited, rejected = (json.loads(record.getMessage()) for record in private.records)
        self.assertEqual(limited["status"], 429)
        self.assertIn("duration_ms", limited)
        self.assertEqual(
            rejected, {"event": "http_request", "route": "stock_search", "status": 503}
        )
