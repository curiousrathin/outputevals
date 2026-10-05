"""Thin wrapper over briefcase-ai's DecisionSnapshot.

The rest of the app talks to `build_snapshot`, never to briefcase directly, so
briefcase API changes stay contained here. Note: briefcase 4.4 uses a builder
API (add_input/add_output/with_*), not the keyword constructor from the plan PDF.

Hashes:
- fingerprint(): inputs + model name only. Same question asked again -> same
  value, so it groups repeated runs for drift scoring.
- content_hash(): the full record (inputs, outputs, params, tags). Use as the
  tamper-evident identity of a single trace.
"""

import json
from typing import Any

from briefcase import DecisionSnapshot, Input, ModelParameters, Output


def _encode(value: Any) -> tuple[str, str]:
    if isinstance(value, str):
        return value, "string"
    return json.dumps(value, default=str, sort_keys=True), "json"


def build_snapshot(
    function_name: str,
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    model: str,
    provider: str = "anthropic",
    params: dict[str, Any] | None = None,
    execution_time_ms: float | None = None,
    tags: dict[str, str] | None = None,
) -> DecisionSnapshot:
    snapshot = DecisionSnapshot(function_name)
    for name, value in inputs.items():
        snapshot.add_input(Input(name, *_encode(value)))
    for name, value in outputs.items():
        snapshot.add_output(Output(name, *_encode(value)))

    model_params = ModelParameters(model).with_provider(provider)
    for key, value in (params or {}).items():
        model_params = model_params.with_parameter(key, value)
    snapshot.with_model_parameters(model_params)

    if execution_time_ms is not None:
        snapshot.with_execution_time(execution_time_ms)
    for key, value in (tags or {}).items():
        snapshot.add_tag(key, value)
    return snapshot
