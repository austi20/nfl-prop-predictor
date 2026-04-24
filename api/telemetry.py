from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor


class _JsonlSpanExporter(SpanExporter):
    def __init__(self, out_dir: Path) -> None:
        self._out_dir = out_dir

    def export(self, spans) -> SpanExportResult:  # type: ignore[override]
        self._out_dir.mkdir(parents=True, exist_ok=True)
        path = self._out_dir / f"spans-{date.today()}.jsonl"
        with path.open("a") as fh:
            for span in spans:
                fh.write(
                    json.dumps(
                        {
                            "name": span.name,
                            "trace_id": f"{span.context.trace_id:032x}",
                            "span_id": f"{span.context.span_id:016x}",
                            "start_ns": span.start_time,
                            "end_ns": span.end_time,
                            "status": span.status.status_code.name,
                            "attributes": dict(span.attributes or {}),
                        }
                    )
                    + "\n"
                )
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass


def setup_telemetry(app: object, telemetry_dir: Path) -> None:
    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(_JsonlSpanExporter(telemetry_dir)))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)  # type: ignore[arg-type]
