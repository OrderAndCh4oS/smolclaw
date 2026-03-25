"""OpenTelemetry tracing for SmolClaw — opt-in, zero-cost no-op when OTEL is not installed."""

import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)

_tracer = None
_initialized = False


# ---------------------------------------------------------------------------
# No-op implementations — used when OTEL packages are not installed
# ---------------------------------------------------------------------------

class NoOpSpan:
    """Zero-cost span that does nothing."""

    def set_attribute(self, key, value):
        pass

    def record_exception(self, exception):
        pass

    def set_status(self, status):
        pass

    def end(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class NoOpTracer:
    """Zero-cost tracer that returns no-op spans."""

    def start_span(self, name, **kwargs):
        return NoOpSpan()

    @contextmanager
    def start_as_current_span(self, name, **kwargs):
        yield NoOpSpan()


_noop_tracer = NoOpTracer()


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def init_tracing(service_name: str = "smolclaw", endpoint: str | None = None):
    """Initialize OpenTelemetry tracing. No-op if OTEL SDK is not installed.

    :param service_name: The service name for OTEL resource.
    :param endpoint: OTLP endpoint URL. Falls back to OTEL_EXPORTER_OTLP_ENDPOINT env var.
    """
    global _tracer, _initialized

    if _initialized:
        return

    _initialized = True

    try:
        import os
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        resolved_endpoint = endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")

        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)

        if resolved_endpoint:
            traces_endpoint = f"{resolved_endpoint.rstrip('/')}/v1/traces"
            exporter = OTLPSpanExporter(endpoint=traces_endpoint)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info("OTEL tracing initialized: endpoint=%s", resolved_endpoint)
        else:
            logger.info("OTEL tracing initialized (no exporter — spans are created but not exported)")

        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(service_name)

    except ImportError:
        logger.debug("OpenTelemetry packages not installed — tracing disabled")
        _tracer = None
    except Exception as e:
        logger.warning("Failed to initialize OTEL tracing: %s", e)
        _tracer = None


def get_tracer():
    """Return the OTEL tracer, or a no-op tracer if OTEL is not available."""
    return _tracer or _noop_tracer


def is_tracing_enabled() -> bool:
    """Return True if a real OTEL tracer is configured."""
    return _tracer is not None


# ---------------------------------------------------------------------------
# Context managers for common span types
# ---------------------------------------------------------------------------

@contextmanager
def trace_agent_turn(session_key: str, iteration: int, model: str = "unknown"):
    """Context manager that creates a span for one agent turn/iteration."""
    tracer = get_tracer()
    with tracer.start_as_current_span("agent.turn") as span:
        span.set_attribute("agent.session_key", session_key)
        span.set_attribute("agent.iteration", iteration)
        span.set_attribute("agent.model", model)
        yield span


@contextmanager
def trace_retrieval(query: str = ""):
    """Context manager for context retrieval spans."""
    tracer = get_tracer()
    with tracer.start_as_current_span("context.retrieval") as span:
        span.set_attribute("retrieval.query", query[:200])
        yield span


@contextmanager
def trace_llm_call(operation: str, model: str = "unknown"):
    """Context manager for LLM API call spans."""
    tracer = get_tracer()
    with tracer.start_as_current_span(f"llm.{operation}") as span:
        span.set_attribute("llm.model", model)
        span.set_attribute("llm.operation", operation)
        yield span
