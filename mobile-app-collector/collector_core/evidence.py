from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path
import json
from typing import Any

CURRENT_EVIDENCE_SCHEMA_VERSION = "1.1"


@dataclass(frozen=True)
class Bounds:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class InteractionEvidence:
    kind: str
    target_element_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    result_screen_id: str | None = None
    result_state_id: str | None = None


@dataclass(frozen=True)
class VisualStyleEvidence:
    background_color: str | None = None
    text_color: str | None = None
    font_size: float | None = None
    font_weight: str | None = None
    corner_radius: float | None = None
    border_color: str | None = None
    border_width: float | None = None
    opacity: float | None = None


@dataclass(frozen=True)
class ElementEvidence:
    evidence_id: str
    role: str
    text: str | None
    bounds: Bounds
    enabled: bool
    selected: bool
    visible: bool
    accessibility_id: str | None = None
    parent_id: str | None = None
    style: VisualStyleEvidence | None = None


@dataclass(frozen=True)
class ScreenEvidence:
    screen_id: str
    state_id: str
    width: int
    height: int
    screenshot_path: str
    screenshot_sha256: str
    ui_tree_path: str | None
    elements: list[ElementEvidence] = field(default_factory=list)
    interactions: list[InteractionEvidence] = field(default_factory=list)


@dataclass(frozen=True)
class FlowStepEvidence:
    source_screen_id: str
    source_state_id: str
    interaction: InteractionEvidence
    target_screen_id: str
    target_state_id: str


@dataclass(frozen=True)
class FlowEvidence:
    flow_id: str
    name: str
    start_screen_id: str
    steps: list[FlowStepEvidence] = field(default_factory=list)


@dataclass(frozen=True)
class AppEvidence:
    app_id: str
    app_name: str
    platform: str
    app_version: str | None
    capture_source: str
    screens: list[ScreenEvidence] = field(default_factory=list)
    flows: list[FlowEvidence] = field(default_factory=list)
    schema_version: str = CURRENT_EVIDENCE_SCHEMA_VERSION



def _schema_major(version: str) -> int:
    try:
        return int(version.split(".", 1)[0])
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid evidence schema version: {version!r}") from exc


def _ensure_supported_schema_version(version: str) -> None:
    current_major = _schema_major(CURRENT_EVIDENCE_SCHEMA_VERSION)
    major = _schema_major(version)
    if major != current_major:
        raise ValueError(
            f"Unsupported evidence schema major version {major}; supported major is {current_major}"
        )


def validate_evidence_graph(app: AppEvidence) -> None:
    """Validate referential integrity before evidence is consumed or persisted."""
    _ensure_supported_schema_version(app.schema_version)

    screen_ids = [screen.screen_id for screen in app.screens]
    if len(screen_ids) != len(set(screen_ids)):
        raise ValueError("Duplicate screen_id detected in evidence")
    screen_by_id = {screen.screen_id: screen for screen in app.screens}

    flow_ids = [flow.flow_id for flow in app.flows]
    if len(flow_ids) != len(set(flow_ids)):
        raise ValueError("Duplicate flow_id detected in evidence")

    for screen in app.screens:
        element_ids = [element.evidence_id for element in screen.elements]
        if len(element_ids) != len(set(element_ids)):
            raise ValueError(f"Duplicate element evidence_id on screen {screen.screen_id}")
        element_id_set = set(element_ids)
        for element in screen.elements:
            if element.parent_id is not None and element.parent_id not in element_id_set:
                raise ValueError(
                    f"Element {element.evidence_id} on screen {screen.screen_id} references unknown parent {element.parent_id}"
                )
        for interaction in screen.interactions:
            if interaction.target_element_id is not None and interaction.target_element_id not in element_id_set:
                raise ValueError(
                    f"Interaction on screen {screen.screen_id} references unknown element {interaction.target_element_id}"
                )
            if interaction.result_screen_id is not None and interaction.result_screen_id not in screen_by_id:
                raise ValueError(
                    f"Interaction on screen {screen.screen_id} references unknown result screen {interaction.result_screen_id}"
                )

    for flow in app.flows:
        if flow.start_screen_id not in screen_by_id:
            raise ValueError(f"Flow {flow.flow_id} references unknown start screen {flow.start_screen_id}")
        for index, step in enumerate(flow.steps):
            if step.source_screen_id not in screen_by_id:
                raise ValueError(
                    f"Flow {flow.flow_id} step {index} references unknown source screen {step.source_screen_id}"
                )
            if step.target_screen_id not in screen_by_id:
                raise ValueError(
                    f"Flow {flow.flow_id} step {index} references unknown target screen {step.target_screen_id}"
                )
            source = screen_by_id[step.source_screen_id]
            target = screen_by_id[step.target_screen_id]
            if step.source_state_id != source.state_id:
                raise ValueError(
                    f"Flow {flow.flow_id} step {index} source state does not match screen state"
                )
            if step.target_state_id != target.state_id:
                raise ValueError(
                    f"Flow {flow.flow_id} step {index} target state does not match screen state"
                )
            if step.interaction.result_screen_id not in {None, step.target_screen_id}:
                raise ValueError(
                    f"Flow {flow.flow_id} step {index} interaction result_screen_id does not match target"
                )
            if step.interaction.result_state_id not in {None, step.target_state_id}:
                raise ValueError(
                    f"Flow {flow.flow_id} step {index} interaction result_state_id does not match target"
                )



def resolve_evidence_asset(evidence_path: str | Path, asset_path: str | Path) -> Path:
    """Resolve evidence asset paths across portable and legacy path forms.

    Preferred evidence stores paths relative to the evidence file. Older runs sometimes stored
    paths relative to the process working directory. This resolver supports both without silently
    inventing a different file.
    """
    evidence_file = Path(evidence_path).resolve()
    asset = Path(asset_path)
    if asset.is_absolute():
        return asset.resolve()
    evidence_relative = (evidence_file.parent / asset).resolve()
    if evidence_relative.exists():
        return evidence_relative
    cwd_relative = asset.resolve()
    if cwd_relative.exists():
        return cwd_relative
    return evidence_relative

def sha256_file(path: str | Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bounds_from_dict(data: dict[str, Any]) -> Bounds:
    return Bounds(**data)


def _element_from_dict(data: dict[str, Any]) -> ElementEvidence:
    style_data = data.get("style")
    return ElementEvidence(
        **{k: v for k, v in data.items() if k not in {"bounds", "style"}},
        bounds=_bounds_from_dict(data["bounds"]),
        style=VisualStyleEvidence(**style_data) if isinstance(style_data, dict) else None,
    )


def _interaction_from_dict(data: dict[str, Any]) -> InteractionEvidence:
    return InteractionEvidence(**data)


def _screen_from_dict(data: dict[str, Any]) -> ScreenEvidence:
    return ScreenEvidence(
        **{k: v for k, v in data.items() if k not in {"elements", "interactions"}},
        elements=[_element_from_dict(item) for item in data.get("elements", [])],
        interactions=[_interaction_from_dict(item) for item in data.get("interactions", [])],
    )


def _flow_step_from_dict(data: dict[str, Any]) -> FlowStepEvidence:
    return FlowStepEvidence(
        **{k: v for k, v in data.items() if k != "interaction"},
        interaction=_interaction_from_dict(data["interaction"]),
    )


def _flow_from_dict(data: dict[str, Any]) -> FlowEvidence:
    return FlowEvidence(
        **{k: v for k, v in data.items() if k != "steps"},
        steps=[_flow_step_from_dict(item) for item in data.get("steps", [])],
    )


def save_evidence(app: AppEvidence, path: str | Path) -> None:
    validate_evidence_graph(app)
    Path(path).write_text(json.dumps(asdict(app), ensure_ascii=False, indent=2), encoding="utf-8")


def load_evidence(path: str | Path) -> AppEvidence:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    metadata = {k: v for k, v in data.items() if k not in {"screens", "flows"}}
    metadata.setdefault("schema_version", "1.0")
    _ensure_supported_schema_version(metadata["schema_version"])
    app = AppEvidence(
        **metadata,
        screens=[_screen_from_dict(item) for item in data.get("screens", [])],
        flows=[_flow_from_dict(item) for item in data.get("flows", [])],
    )
    validate_evidence_graph(app)
    return app
