from __future__ import annotations

from steelman.image_values import extract_image_references


def test_extract_image_references_from_nested_values() -> None:
    values = {
        "admissionController": {
            "image": {
                "repository": "ghcr.io/kyverno/kyverno",
                "tag": "v1.13.0",
            }
        },
        "backgroundController": {
            "image": "ghcr.io/kyverno/background-controller:v1.13.0"
        },
    }
    refs = extract_image_references(values)
    assert [ref.path for ref in refs] == [
        "admissionController.image.repository",
        "backgroundController.image",
    ]
