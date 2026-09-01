"""Observability adapter (OpenLIT).

Initializes OpenLIT tracing/metrics and exposes a metrics sink shaped like the
in-tree ``InMemoryMetrics`` (:mod:`icm_harness.observability.metrics`) so the
application layer can swap it in. Raises :class:`IntegrationUnavailable` when
OpenLIT is not installed.
"""

from __future__ import annotations


def initialize_openlit(**kwargs):
    try:
        import openlit
    except ImportError as exc:
        from icm_harness.kernel.errors import IntegrationUnavailable

        raise IntegrationUnavailable("OpenLIT is not installed") from exc
    return openlit.init(**kwargs)


class OpenLITMetrics:
    """Counter sink matching the InMemoryMetrics interface, forwarding to OTEL."""

    def __init__(self, meter=None):
        self._meter = meter
        self._counters: dict[str, float] = {}
        self._instruments: dict[str, object] = {}

    def _instrument(self, name: str):
        if self._meter is None:
            return None
        instrument = self._instruments.get(name)
        if instrument is None:
            instrument = self._meter.create_counter(name)
            self._instruments[name] = instrument
        return instrument

    def increment(self, name: str, value: float = 1.0) -> None:
        self._counters[name] = self._counters.get(name, 0.0) + value
        instrument = self._instrument(name)
        if instrument is not None:
            instrument.add(value)

    def get(self, name: str) -> float:
        return self._counters.get(name, 0.0)
