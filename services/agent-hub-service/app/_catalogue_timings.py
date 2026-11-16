"""Request-local, fail-open observations without request or trace-info inspection."""

import logging
import math
import time
from contextlib import contextmanager

_LOGGER = logging.getLogger("uvicorn.error.hub_catalogue_producer")
_MAX_SAMPLES = 64
_TRACE_EVENTS = {
    f"connection.{name}.{event}": (name, event)
    for name in ("connect_tcp", "start_tls")
    for event in ("started", "complete", "failed")
}


def _now(clock):
    try:
        value = clock()
        if type(value) in (int, float) and math.isfinite(value) and value >= 0:
            return float(value)
    except Exception:
        pass
    return None


class _Duration:
    def __init__(self):
        self.elapsed, self.samples, self.unknown = 0.0, 0, False

    def start(self, clock):
        if self.samples >= _MAX_SAMPLES:
            self.unknown = True
            return None
        self.samples += 1
        value = _now(clock)
        if value is None:
            self.unknown = True
        return value

    def finish(self, clock, started):
        ended = _now(clock)
        if started is None or ended is None or ended < started:
            self.unknown = True
            return
        self.elapsed += ended - started

    @contextmanager
    def measure(self, clock):
        started = self.start(clock)
        try:
            yield
        finally:
            self.finish(clock, started)

    def text(self):
        value = self.elapsed * 1000
        if self.unknown or not math.isfinite(value):
            return "unknown"
        return f"{value:.3f}" if self.samples else "not_observed"


class _ProducerTiming:
    def __init__(self, clock):
        self.clock = clock
        self.durations = {
            name: _Duration()
            for name in ("token", "sign", "producer_io", "connect_tcp", "start_tls")
        }
        self.started = {}

    def measure(self, stage):
        return self.durations[stage].measure(self.clock)

    def trace(self, event_name, _info):
        # Only six exact event names are examined. In particular, never inspect,
        # stringify or retain info: it may contain requests, credentials or errors.
        try:
            self._trace_event(event_name)
        except Exception:
            self.durations["connect_tcp"].unknown = True
            self.durations["start_tls"].unknown = True

    def _trace_event(self, event_name):
        if type(event_name) is not str or event_name not in _TRACE_EVENTS:
            return
        name, event = _TRACE_EVENTS[event_name]
        duration = self.durations[name]
        if event == "started":
            if name in self.started:
                duration.unknown = True
            self.started[name] = duration.start(self.clock)
        elif name in self.started:
            duration.finish(self.clock, self.started.pop(name))
        else:
            duration.unknown = True


class CatalogueTimings:
    """Two fixed aggregate lines; no cached authority, credentials or raw events."""

    def __init__(self, *, clock=None):
        self.clock = time.perf_counter if clock is None else clock
        self.client_setup = _Duration()
        self.producers = {name: _ProducerTiming(self.clock) for name in ("user", "portfolio")}

    def setup(self):
        return self.client_setup.measure(self.clock)

    def emit(self):
        for service, producer in self.producers.items():
            try:
                for name in producer.started:
                    producer.durations[name].unknown = True
                values = producer.durations
                _LOGGER.info(
                    "hub_catalogue_producer service=%s token_ms=%s sign_ms=%s "
                    "shared_client_setup_ms=%s producer_io_ms=%s connect_tcp_ms=%s start_tls_ms=%s "
                    "token_calls=%d sign_calls=%d producer_io_calls=%d "
                    "connect_tcp_calls=%d start_tls_calls=%d",
                    service,
                    values["token"].text(),
                    values["sign"].text(),
                    self.client_setup.text(),
                    values["producer_io"].text(),
                    values["connect_tcp"].text(),
                    values["start_tls"].text(),
                    *(values[name].samples for name in values),
                )
            except Exception:
                # A failed observer/logger must not replace a producer result or
                # its original exception. Missing diagnostics never mean 0 ms.
                pass
