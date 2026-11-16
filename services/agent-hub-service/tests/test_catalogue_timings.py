"""Closed observer controls over real HTTPcore streams and synthetic owner proofs."""

import logging
import socket
import ssl
import unittest
from unittest.mock import patch

import httpcore
import httpx
from test_catalogue import PORTFOLIO, USER, CatalogueFixture

from app._catalogue_timings import _LOGGER, _MAX_SAMPLES, CatalogueTimings

CANARY = "synthetic-secret-header-body-url-exception-canary"


class Clock:
    def __init__(self):
        self.value = 10.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class PoisonInfo:
    def __getattribute__(self, name):
        raise AssertionError("Trace info must not be inspected: " + CANARY)


class MemoryStream(httpcore.NetworkStream):
    def __init__(self, clock, *, fail_tls=False):
        self.clock, self.fail_tls, self.closed = clock, fail_tls, False
        body = CANARY.encode()
        self.reply = (
            b"HTTP/1.1 200 OK\r\nContent-Length: "
            + str(len(body)).encode()
            + b"\r\nX-Private-Canary: "
            + body
            + b"\r\n\r\n"
            + body
        )

    def read(self, max_bytes, timeout=None):
        self.clock.advance(0.04)
        result, self.reply = self.reply[:max_bytes], self.reply[max_bytes:]
        return result

    def write(self, buffer, timeout=None):
        pass

    def close(self):
        self.closed = True

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self.clock.advance(0.03)
        if self.fail_tls:
            raise httpcore.ConnectError(CANARY)
        if not ssl_context.check_hostname or ssl_context.verify_mode != ssl.CERT_REQUIRED:
            raise AssertionError("TLS verification must remain enabled")
        return self

    def get_extra_info(self, info):
        return None


class MemoryBackend(httpcore.NetworkBackend):
    def __init__(self, clock, *, fail_tls=False, fail_tcp=False):
        self.clock, self.fail_tls, self.fail_tcp = clock, fail_tls, fail_tcp
        self.streams = []

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.clock.advance(0.02)
        if self.fail_tcp:
            raise httpcore.ConnectError(CANARY)
        stream = MemoryStream(self.clock, fail_tls=self.fail_tls)
        self.streams.append(stream)
        return stream


def real_core_request(timing, clock, *, fail_tls=False, fail_tcp=False):
    backend = MemoryBackend(clock, fail_tls=fail_tls, fail_tcp=fail_tcp)
    transport = httpx.HTTPTransport(trust_env=False, retries=0)
    transport._pool.close()
    transport._pool = httpcore.ConnectionPool(
        network_backend=backend, ssl_context=ssl.create_default_context(), retries=0
    )
    with patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")):
        with httpx.Client(transport=transport, trust_env=False, follow_redirects=False) as client:
            with timing.measure("producer_io"):
                with client.stream(
                    "GET",
                    "https://synthetic.invalid/" + CANARY,
                    headers={"Authorization": "Bearer " + CANARY},
                    timeout=httpx.Timeout(4),
                    extensions={"trace": timing.trace},
                ) as response:
                    return response.read(), backend


class ObserverTests(unittest.TestCase):
    def test_only_six_events_are_observed_without_touching_info(self):
        clock = Clock()
        timing = CatalogueTimings(clock=clock)
        producer = timing.producers["user"]
        info = PoisonInfo()
        producer.trace("http11.receive_response_headers.complete", info)
        producer.trace(object(), info)
        producer.trace("connection.connect_tcp.started", info)
        clock.advance(0.02)
        producer.trace("connection.connect_tcp.complete", info)
        producer.trace("connection.start_tls.started", info)
        clock.advance(0.03)
        producer.trace("connection.start_tls.failed", info)
        with self.assertLogs(_LOGGER, logging.INFO) as logs:
            timing.emit()
        self.assertEqual(len(logs.output), 2)
        self.assertIn("connect_tcp_ms=20.000 start_tls_ms=30.000", logs.output[0])
        self.assertIn("token_ms=not_observed", logs.output[0])
        self.assertIn("connect_tcp_ms=not_observed", logs.output[1])
        self.assertNotIn(CANARY, " ".join(logs.output))

    def test_real_httpcore_tcp_tls_streams_and_failures_remain_original(self):
        for failed in (None, "tcp", "tls"):
            clock = Clock()
            timing = CatalogueTimings(clock=clock)
            with self.assertLogs(_LOGGER, logging.INFO) as logs:
                if failed:
                    with self.assertRaisesRegex(httpx.ConnectError, CANARY):
                        real_core_request(
                            timing.producers["user"],
                            clock,
                            fail_tls=failed == "tls",
                            fail_tcp=failed == "tcp",
                        )
                else:
                    body, backend = real_core_request(timing.producers["user"], clock)
                    self.assertEqual(body, CANARY.encode())
                    self.assertEqual(len(backend.streams), 1)
                    self.assertTrue(backend.streams[0].closed)
                timing.emit()
            self.assertEqual(len(logs.output), 2)
            self.assertIn("connect_tcp_ms=20.000", logs.output[0])
            self.assertIn(
                "start_tls_ms=not_observed" if failed == "tcp" else "start_tls_ms=30.000",
                logs.output[0],
            )
            self.assertIn(
                "connect_tcp_calls=1 start_tls_calls=0"
                if failed == "tcp"
                else "connect_tcp_calls=1 start_tls_calls=1",
                logs.output[0],
            )
            self.assertNotIn(CANARY, " ".join(logs.output))

    def test_bad_trace_clock_and_logger_cannot_replace_results_or_errors(self):
        clock = Clock()
        timing = CatalogueTimings(clock=clock)
        with patch.object(
            timing.producers["user"], "_trace_event", side_effect=RuntimeError(CANARY)
        ):
            body, _ = real_core_request(timing.producers["user"], clock)
        self.assertEqual(body, CANARY.encode())
        with self.assertLogs(_LOGGER, logging.INFO) as logs:
            timing.emit()
        self.assertIn("connect_tcp_ms=unknown start_tls_ms=unknown", logs.output[0])
        with patch.object(_LOGGER, "info", side_effect=RuntimeError(CANARY)):
            timing.emit()

        broken = CatalogueTimings(clock=lambda: float("nan"))
        with broken.producers["user"].measure("token"):
            pass
        with self.assertLogs(_LOGGER, logging.INFO) as logs:
            broken.emit()
        self.assertIn("token_ms=unknown", logs.output[0])
        with patch.object(_LOGGER, "info", side_effect=RuntimeError(CANARY)):
            with self.assertRaisesRegex(httpx.ConnectError, CANARY):
                try:
                    real_core_request(broken.producers["user"], clock, fail_tls=True)
                finally:
                    broken.emit()

    def test_unfinished_or_overflowed_samples_are_unknown_and_counts_stay_bounded(self):
        timing = CatalogueTimings(clock=Clock())
        producer = timing.producers["user"]
        for _ in range(_MAX_SAMPLES + 5):
            with producer.measure("token"):
                pass
        producer.trace("connection.connect_tcp.started", PoisonInfo())
        with self.assertLogs(_LOGGER, logging.INFO) as logs:
            timing.emit()
        self.assertIn("token_ms=unknown", logs.output[0])
        self.assertIn("token_calls=64", logs.output[0])
        self.assertIn("connect_tcp_ms=unknown", logs.output[0])


class CatalogueTimingTests(CatalogueFixture, unittest.TestCase):
    def test_fixed_two_lines_keep_fresh_credentials_original_results_and_no_trace_assumption(self):
        with patch.object(self.signer, "sign", wraps=self.signer.sign) as sign:
            with self.assertLogs(_LOGGER, logging.INFO) as logs:
                result = self.read()
        self.assertEqual(len(self.token_calls), 2)
        self.assertEqual(sign.call_count, 2)
        self.assertEqual(set(self.token_calls), {USER, PORTFOLIO})
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(len(result["groups"]), 3)
        rows = [line for line in logs.output if "hub_catalogue_producer " in line]
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertIn("token_calls=1 sign_calls=1 producer_io_calls=1", row)
            self.assertIn("connect_tcp_ms=not_observed start_tls_ms=not_observed", row)
            self.assertNotIn(self.fixture.owner, row)
            self.assertNotIn("Bearer", row)
        self.assertEqual(
            rows[0].split("shared_client_setup_ms=")[1].split()[0],
            rows[1].split("shared_client_setup_ms=")[1].split()[0],
        )

    def test_observation_failures_do_not_change_data_deadline_clock_or_fresh_signing(self):
        baseline = self.read()
        observed = CatalogueTimings(clock=lambda: (_ for _ in ()).throw(RuntimeError(CANARY)))
        with patch("app.catalogue.CatalogueTimings", return_value=observed):
            with patch.object(_LOGGER, "info", side_effect=RuntimeError(CANARY)):
                actual = self.read()
        self.assertEqual(actual, baseline)
        self.assertEqual(len(self.token_calls), 4)
        self.assertEqual(len(self.calls), 4)

    def test_broken_emitter_preserves_success_and_an_original_construction_error(self):
        with patch("app.catalogue.CatalogueTimings.emit", side_effect=RuntimeError(CANARY)):
            self.assertEqual(len(self.read()["groups"]), 3)
            with patch("app.catalogue.httpx.Client", side_effect=ValueError("original-failure")):
                with self.assertRaisesRegex(ValueError, "original-failure"):
                    self.sources.discover("synthetic-owner", [])

    def test_producer_error_never_reads_or_logs_its_private_body(self):
        class ForbiddenBody(httpx.SyncByteStream):
            def __iter__(self):
                raise AssertionError(CANARY)

        def handler(request):
            if str(request.url).startswith(PORTFOLIO):
                self.principal(request)
                return httpx.Response(503, stream=ForbiddenBody())
            return self.handle(request)

        with self.assertLogs(_LOGGER, logging.INFO) as logs:
            result = self.read(sources=self.make_sources(transport=httpx.MockTransport(handler)))
        holdings = next(group for group in result["groups"] if group["kind"] == "holdings")
        self.assertEqual(holdings["items"][0]["state"], "unavailable")
        self.assertNotIn(CANARY, " ".join(logs.output))
        self.assertEqual(sum("hub_catalogue_producer " in line for line in logs.output), 2)


if __name__ == "__main__":
    unittest.main()
