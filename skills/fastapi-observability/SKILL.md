---
name: fastapi-observability
description: >
  Implement observability for FastAPI: structured logging with request IDs,
  Prometheus metrics (latency, throughput, errors, saturation), OpenTelemetry
  distributed tracing, healthcheck and readiness endpoints, Sentry error
  reporting, and SLO/SLI definition. Use this skill whenever the user asks
  about metrics, monitoring, tracing, OpenTelemetry, OTel, Prometheus,
  Grafana, healthcheck, /health, /ready, Sentry, alerts, SLO, SLI, or "how
  do I know if my API is healthy". Python 3.12+, OTel SDK, prometheus-client.
---

# FastAPI Observability Skill

Three pillars (logs, metrics, traces) + healthchecks + error reporting. Python 3.12+.

---

## Pillar Roles

| Pillar | Question it answers | Tool |
|--------|---------------------|------|
| **Logs** | What happened in this specific request? | structured JSON → Loki / CloudWatch |
| **Metrics** | What's the rate/latency/error% across all requests? | Prometheus + Grafana |
| **Traces** | Where did the time go in this request, across services? | OpenTelemetry → Jaeger/Tempo/Datadog |
| **Errors** | Who's hitting this exception, with what context? | Sentry |
| **Health** | Should the load balancer route traffic here? | `/health`, `/ready` |

Don't pick one — they answer different questions.

---

## Healthcheck vs Readiness

```python
# app/api/health.py
from fastapi import APIRouter, status
from sqlalchemy import text
from app.config.database import engine

router = APIRouter(tags=["meta"])

@router.get("/health", status_code=200, include_in_schema=False)
async def liveness():
    """Process is alive. No external deps. K8s liveness probe."""
    return {"status": "ok"}

@router.get("/ready", include_in_schema=False)
async def readiness():
    """Can serve traffic — DB + Redis reachable. K8s readiness probe."""
    checks = {}
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as e:
        checks["db"] = f"fail: {type(e).__name__}"
    # ... redis, downstream services
    healthy = all(v == "ok" for v in checks.values())
    return JSONResponse(
        {"status": "ok" if healthy else "degraded", "checks": checks},
        status_code=200 if healthy else 503,
    )
```

**Liveness** = "restart me if I'm broken." Must NOT depend on DB — DB outage shouldn't kill pods.
**Readiness** = "stop sending me traffic if my deps are down."

---

## Prometheus Metrics

```python
# app/middleware/metrics.py
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
import time

REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)

LATENCY = Histogram(
    "http_request_duration_seconds",
    "Request latency",
    ["method", "path"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start
        # Use route template, not request.url.path — prevents cardinality blowup
        route = request.scope.get("route")
        path = route.path if route else request.url.path
        REQUESTS.labels(request.method, path, response.status_code).inc()
        LATENCY.labels(request.method, path).observe(elapsed)
        return response


def metrics_endpoint():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
```

Wire it:
```python
app.add_middleware(PrometheusMiddleware)
app.add_route("/metrics", metrics_endpoint, include_in_schema=False)
```

**Critical: use the route template (`/users/{user_id}`), not the actual path (`/users/42`).** Otherwise label cardinality explodes and Prometheus dies.

### The Four Golden Signals

For every service, measure:
1. **Latency** — `http_request_duration_seconds` (p50, p95, p99)
2. **Traffic** — `rate(http_requests_total[1m])`
3. **Errors** — `rate(http_requests_total{status=~"5.."}[1m])`
4. **Saturation** — pool usage: `db_pool_in_use`, `redis_pool_in_use`, queue depth

Custom business metrics (orders/min, sign-ups/hour) live alongside.

---

## Distributed Tracing (OpenTelemetry)

```python
# app/observability/tracing.py
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

def setup_tracing(app, *, service_name: str, otlp_endpoint: str) -> None:
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
    RedisInstrumentor().instrument()
    HTTPXClientInstrumentor().instrument()
```

In `main.py`:
```python
if settings.OTEL_EXPORTER_OTLP_ENDPOINT:
    setup_tracing(app, service_name="erp-api", otlp_endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT)
```

### Custom spans for business steps

```python
from opentelemetry import trace
tracer = trace.get_tracer(__name__)

async def issue_invoice(payload: InvoiceCreate):
    with tracer.start_as_current_span("invoice.issue") as span:
        span.set_attribute("customer.id", payload.customer_id)
        span.set_attribute("amount", float(payload.amount))
        # ...
```

Span attributes become searchable in Jaeger/Tempo. Don't put PII in attributes.

### Trace context propagation

OTel auto-propagates `traceparent` headers via `httpx`/`requests` instrumentors. Across services in the same trace, you can follow a request from FE → API → background job → DB.

---

## Correlate Logs with Traces

In your log middleware (see `fastapi-logging`), attach the active trace ID:

```python
from opentelemetry import trace as otel_trace

span = otel_trace.get_current_span()
ctx = span.get_span_context() if span else None
log_extra = {
    "trace_id": f"{ctx.trace_id:032x}" if ctx and ctx.is_valid else None,
    "span_id": f"{ctx.span_id:016x}" if ctx and ctx.is_valid else None,
    "request_id": request_id,
}
```

Now in Grafana you can click a log → jump to its trace.

---

## Sentry (Error Tracking)

```python
# app/observability/errors.py
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

def setup_sentry() -> None:
    if not settings.SENTRY_DSN:
        return
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN.get_secret_value(),
        environment=settings.ENV,
        release=settings.APP_VERSION,
        traces_sample_rate=0.1,           # 10% of traces
        profiles_sample_rate=0.05,
        integrations=[StarletteIntegration(), FastApiIntegration()],
        send_default_pii=False,           # never send IPs/headers/cookies
        before_send=scrub_sensitive,
    )

def scrub_sensitive(event, hint):
    # Strip auth headers, body fields named password/token/etc.
    ...
    return event
```

Tag every event with `tenant_id`, `user_id` (hashed), `request_id` so you can group.

Don't use Sentry as a log store — only exceptions. For warnings/info, use logs.

---

## SLO / SLI Examples

Define SLOs **before** they're violated:

```yaml
# slo.yaml — written, reviewed, alerted on
- name: erp-api availability
  sli: rate(http_requests_total{status!~"5.."}[5m]) / rate(http_requests_total[5m])
  target: 99.5%
  window: 30d

- name: erp-api latency
  sli: histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))
  target: < 500ms
  window: 30d
```

Alert on **error budget burn**, not raw thresholds — fewer false positives.

---

## What to Track Per Endpoint

For business-critical endpoints, add custom metrics:

```python
INVOICES_ISSUED = Counter("erp_invoices_issued_total", "Invoices issued", ["tenant_id"])
INVOICE_AMOUNT = Histogram("erp_invoice_amount_dollars", "Invoice amount", ["tenant_id"])

async def issue_invoice(...):
    ...
    INVOICES_ISSUED.labels(tenant_id=tenant.id).inc()
    INVOICE_AMOUNT.labels(tenant_id=tenant.id).observe(float(invoice.amount))
```

Keep label cardinality bounded. `tenant_id` for 100 tenants is fine; per-user is not.

---

## Anti-patterns

| Don't | Why |
|------|-----|
| Label metrics with `user_id` or raw `path` | Cardinality blowup, Prometheus melts |
| Use `print()` for "debug logs" | No structure, no level, no correlation |
| Liveness probe hits the DB | DB blip → all pods restart → outage amplified |
| Sample traces at 100% in prod | Massive cost, ingest pipeline drops anyway |
| Catch + swallow exceptions silently | Sentry never sees them; user confused |
| Log + raise + Sentry-capture the same exception | Triple-counted alerts |
| Custom metrics with PII labels | Compliance violation, retention nightmare |

---

## Verification Checklist

- [ ] `/health` doesn't touch DB; `/ready` does
- [ ] Prometheus `/metrics` uses route templates only
- [ ] OTel auto-instrumentation enabled for FastAPI/SQLAlchemy/HTTPX/Redis
- [ ] Logs include `trace_id` and `request_id`
- [ ] Sentry initialized with `send_default_pii=False`
- [ ] Trace sample rate ≤ 0.2 in prod
- [ ] SLO doc committed; dashboard exists; alert rules in code
- [ ] Load test confirms `/metrics` cardinality is bounded
