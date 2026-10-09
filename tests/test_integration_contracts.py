"""Integration: typed contracts between modules (footprints <-> geometry <-> API schema)."""
from __future__ import annotations

from partforge import footprints as fp
from partforge.footprints.models import FootprintPreview
from partforge.geometry.model import FootprintSpec


def test_footprint_preview_spec_is_typed() -> None:
    assert FootprintPreview.model_fields["spec"].annotation is FootprintSpec
    preview = fp.preview(fp.chip_request("R", "0603"), svg=False)
    assert isinstance(preview.spec, FootprintSpec) and preview.spec.name == "RESC1608X50N"
    # JSON round trip (API, frontend) keeps the geometry model
    again = FootprintPreview.model_validate_json(preview.model_dump_json())
    assert isinstance(again.spec, FootprintSpec) and again.spec == preview.spec
    schema = FootprintPreview.model_json_schema()
    assert schema["properties"]["spec"] == {"$ref": "#/$defs/FootprintSpec"}


def test_openapi_schema_builds_with_typed_previews() -> None:
    from partforge.app import create_app

    openapi = create_app(token="x").openapi()
    components = openapi["components"]["schemas"]
    assert "FootprintSpec" in components and "FootprintPreviewOut" in components
    assert components["FootprintPreviewOut"]["properties"]["spec"] == {"$ref": "#/components/schemas/FootprintSpec"}
