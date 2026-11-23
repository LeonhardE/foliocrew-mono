"""Pinned actual MCP SDK over the bootstrap-only native credential profile."""

import asyncio
import json
import os
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

import httpx2
import test_native_transport as accounts
from fastapi import FastAPI
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from app.native_mcp import install_native_mcp


class NativeMCPTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.case = accounts.NativeTransportTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.oauth = self.case.service
        self.token = self.case.connect()["access_token"]
        env = patch.dict(
            os.environ,
            {
                "HUB_PERSISTENT_TRANSPORT_ENABLED": "1",
                "HUB_PERSISTENT_MCP_ENABLED": "1",
                "HUB_AGENT_OWNED_CREDENTIALS_ENABLED": "1",
                "HUB_AGENT_OWNER_URL": "https://owner.example/agents",
                "CORS_ORIGINS": "https://owner.example",
            },
        )
        env.start()
        self.addCleanup(env.stop)
        clock = patch(
            "mcp.server.auth.middleware.bearer_auth.time",
            SimpleNamespace(time=lambda: self.case.now),
        )
        clock.start()
        self.addCleanup(clock.stop)
        self.app = FastAPI()
        self.boundary = install_native_mcp(self.app, factory=lambda: self.oauth)

    @asynccontextmanager
    async def sdk_requests(self, *, processing_delay=0):
        async with self.app.router.lifespan_context(self.app):
            application = self.boundary.application
            calls = []

            async def counted(scope, receive, send):
                calls.append(scope["path"])
                await asyncio.sleep(processing_delay)
                return await application(scope, receive, send)

            self.boundary.application = counted
            try:
                yield calls
            finally:
                self.boundary.application = application

    async def boundary_request(self, receive, *, sent=None, send_delay=0):
        messages = [] if sent is None else sent
        host = urlsplit(self.oauth.config.base.issuer).netloc
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": "/mcp/v3",
            "raw_path": b"/mcp/v3",
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"host", host.encode()),
                (b"authorization", b"Bearer synthetic_invalid_credential"),
                (b"content-type", b"application/json"),
            ],
            "server": (host, 443),
            "client": ("127.0.0.1", 12345),
        }

        async def send(message):
            messages.append(message)
            await asyncio.sleep(send_delay)

        await self.app(scope, receive, send)
        return messages

    def assert_rejected(self, messages, status, code):
        start = next(message for message in messages if message["type"] == "http.response.start")
        self.assertEqual(status, start["status"])
        self.assertEqual(b"no-store", dict(start["headers"])[b"cache-control"])
        body = b"".join(
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        )
        self.assertEqual({"error": code}, json.loads(body))
        self.assertNotIn(b"synthetic_invalid_credential", body)

    @asynccontextmanager
    async def client(self, mode="auto"):
        async with self.app.router.lifespan_context(self.app):
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=self.app),
                headers={"Authorization": "Bearer " + self.token},
            ) as http:
                async with Client(
                    streamable_http_client(
                        self.oauth.config.base.issuer + "/mcp/v3", http_client=http
                    ),
                    mode=mode,
                ) as client:
                    yield client

    async def test_legacy_sdk_protocol_uses_only_current_personal_agent_tools(self):
        async with self.client("legacy") as client:
            result = await client.call_tool("agent_connection", {})
            self.assertFalse(result.is_error)
            self.assertIn(
                "continue onboarding after account linking",
                result.structured_content["hostInstructions"],
            )
            self.assertEqual(result.structured_content["provider"], "muse")

    async def test_wrong_host_origin_ambient_authority_and_unknown_paths_are_closed(self):
        async with self.app.router.lifespan_context(self.app):
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=self.app)) as http:
                url = self.oauth.config.base.issuer + "/mcp/v3"
                good = {"Authorization": "Bearer " + self.token, "Content-Type": "application/json"}
                cases = [
                    await http.post(url, json={}, headers={**good, "Host": "wrong.example"}),
                    await http.post(
                        url, json={}, headers={**good, "Origin": self.oauth.config.issuer}
                    ),
                    await http.post(url + "?owner=other", json={}, headers=good),
                    await http.post(
                        url, json={}, headers={**good, "X-FolioView-Delegation": "private_marker"}
                    ),
                    await http.get(url, headers=good),
                ]
                self.assertEqual([r.status_code for r in cases], [403, 403, 400, 400, 405])
                self.assertTrue(all("private_marker" not in r.text for r in cases))

    async def test_owned_sdk_has_only_private_host_bootstrap_and_opaque_offers(self):
        from folioview_shared.encrypted.jsonutil import b64url_encode

        with patch.dict(
            os.environ,
            {
                "HUB_AGENT_OWNED_CREDENTIALS_ENABLED": "1",
                "HUB_AGENT_OWNER_URL": "https://owner.example/agents",
                "CORS_ORIGINS": "https://owner.example",
            },
        ):
            async with self.client() as client:
                tools = await client.list_tools()
                self.assertEqual(
                    {t.name for t in tools.tools},
                    {
                        "agent_connection",
                        "prepare_agent_authorization",
                        "submit_agent_offer",
                        "agent_activation",
                    },
                )
                inspected = await client.call_tool("agent_connection", {})
                self.assertFalse(inspected.is_error)
                self.assertEqual(inspected.structured_content["provider"], "muse")
                prepared = await client.call_tool("prepare_agent_authorization", {})
                self.assertFalse(prepared.is_error)
                setup = prepared.structured_content["setup"]["setupIntentId"]
                offer = await client.call_tool(
                    "submit_agent_offer",
                    {
                        "setupIntentId": setup,
                        "offer": {
                            "version": 1,
                            "iv": b64url_encode(b"i" * 12),
                            "ciphertext": b64url_encode(b"c" * 32),
                        },
                    },
                )
                self.assertFalse(offer.is_error)
                pending = await client.call_tool("agent_activation", {"setupIntentId": setup})
                self.assertFalse(pending.is_error)
                self.assertIsNone(pending.structured_content["activation"])
                for name, args in [
                    ("open_persistent_runtime", {}),
                    ("prepare_agent_authorization", {"provider": "chatgpt"}),
                    (
                        "submit_agent_offer",
                        {"setupIntentId": setup, "offer": {"privateKey": "synthetic_marker"}},
                    ),
                ]:
                    rejected = await client.call_tool(name, args)
                    self.assertTrue(rejected.is_error)
                    self.assertNotIn("synthetic_marker", str(rejected))
                self.assertNotIn(self.token, str(prepared.structured_content))

    async def test_disabled_surface_returns_closed_error_without_creating_setup(self):
        with patch.dict(os.environ, {"HUB_PERSISTENT_MCP_ENABLED": "0"}):
            async with self.app.router.lifespan_context(self.app):
                async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=self.app)) as http:
                    response = await http.post(self.oauth.config.base.issuer + "/mcp/v3", json={})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers["cache-control"], "no-store")

    async def test_stalled_body_times_out_before_sdk_with_fixed_private_error(self):
        received = False
        blocked = asyncio.Event()

        async def receive():
            nonlocal received
            if not received:
                received = True
                return {"type": "http.request", "body": b"{", "more_body": True}
            await blocked.wait()
            raise AssertionError("the stalled body must be cancelled")

        async with self.sdk_requests() as calls:
            with patch("app.native_mcp.BODY_READ_TIMEOUT_SECONDS", 0.02):
                messages = await asyncio.wait_for(self.boundary_request(receive), 1)
            self.assertEqual([], calls)
        self.assert_rejected(messages, 400, "malformed_request")

    async def test_body_deadline_is_total_not_reset_for_each_chunk(self):
        chunks = iter([b"{", b" ", b"}"])

        async def receive():
            await asyncio.sleep(0.03)
            chunk = next(chunks)
            return {"type": "http.request", "body": chunk, "more_body": chunk != b"}"}

        async with self.sdk_requests() as calls:
            with patch("app.native_mcp.BODY_READ_TIMEOUT_SECONDS", 0.05):
                messages = await asyncio.wait_for(self.boundary_request(receive), 1)
            self.assertEqual([], calls)
        self.assert_rejected(messages, 400, "malformed_request")

    async def test_disconnect_during_body_stops_without_sdk_or_partial_response(self):
        messages = iter(
            [
                {"type": "http.request", "body": b"{", "more_body": True},
                {"type": "http.disconnect"},
            ]
        )

        async def receive():
            return next(messages)

        async with self.sdk_requests() as calls:
            self.assertEqual([], await self.boundary_request(receive))
            self.assertEqual([], calls)

    async def test_external_cancellation_propagates_without_sdk_or_response(self):
        entered, blocked = asyncio.Event(), asyncio.Event()
        sent = []

        async def receive():
            entered.set()
            await blocked.wait()
            raise AssertionError("the cancelled request must not resume")

        async with self.sdk_requests() as calls:
            pending = asyncio.create_task(self.boundary_request(receive, sent=sent))
            await asyncio.wait_for(entered.wait(), 1)
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await pending
            self.assertEqual([], calls)
            self.assertEqual([], sent)

    async def test_overflow_is_rejected_before_extending_the_bounded_buffer(self):
        for chunks, expected_extensions in (([b"x" * 9], []), ([b"x" * 8, b"y"], [8])):
            with self.subTest(chunk_sizes=[len(chunk) for chunk in chunks]):
                extensions = []
                messages = iter(chunks)

                class TrackedBody(bytearray):
                    def extend(self, value, _extensions=extensions):
                        _extensions.append(len(self) + len(value))
                        return super().extend(value)

                async def receive(_messages=messages):
                    return {"type": "http.request", "body": next(_messages), "more_body": True}

                async with self.sdk_requests() as calls:
                    with (
                        patch("app.native_mcp.MAX_HTTP_WRITE_BYTES", 8),
                        patch("app.native_mcp.bytearray", TrackedBody, create=True),
                    ):
                        sent = await self.boundary_request(receive)
                    self.assertEqual([], calls)
                self.assertEqual(expected_extensions, extensions)
                self.assert_rejected(sent, 413, "payload_too_large")

    async def test_exact_byte_limit_reaches_real_sdk_and_still_rejects_invalid_token(self):
        async def receive():
            return {"type": "http.request", "body": b"{}", "more_body": False}

        async with self.sdk_requests() as calls:
            with patch("app.native_mcp.MAX_HTTP_WRITE_BYTES", 2):
                messages = await self.boundary_request(receive)
            self.assertEqual(["/mcp/v3"], calls)
        start = next(message for message in messages if message["type"] == "http.response.start")
        self.assertEqual(401, start["status"])
        self.assertEqual(b"no-store", dict(start["headers"])[b"cache-control"])

    async def test_body_deadline_does_not_shorten_sdk_processing(self):
        async def receive():
            return {"type": "http.request", "body": b"{}", "more_body": False}

        async with self.sdk_requests(processing_delay=0.05) as calls:
            with patch("app.native_mcp.BODY_READ_TIMEOUT_SECONDS", 0.02):
                messages = await self.boundary_request(receive)
            self.assertEqual(["/mcp/v3"], calls)
        self.assertEqual(401, messages[0]["status"])

    async def test_body_deadline_does_not_interrupt_error_response_sending(self):
        async def receive():
            return {"type": "http.request", "body": b"xx", "more_body": False}

        async with self.sdk_requests() as calls:
            with (
                patch("app.native_mcp.BODY_READ_TIMEOUT_SECONDS", 0.02),
                patch("app.native_mcp.MAX_HTTP_WRITE_BYTES", 1),
            ):
                messages = await self.boundary_request(receive, send_delay=0.03)
            self.assertEqual([], calls)
        self.assertEqual(1, sum(m["type"] == "http.response.start" for m in messages))
        self.assert_rejected(messages, 413, "payload_too_large")
