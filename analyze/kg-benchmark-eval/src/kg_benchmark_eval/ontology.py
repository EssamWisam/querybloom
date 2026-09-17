"""Ontology loading and provenance for class and property universes."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_META_PREFIXES = (
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "http://www.w3.org/2000/01/rdf-schema#",
    "http://www.w3.org/2002/07/owl#",
    "http://www.w3.org/2001/XMLSchema#",
)


class OntologyLoadError(ValueError):
    """Raised when an ontology source exists but cannot be decoded."""


@dataclass(frozen=True)
class OntologySource:
    """Source file and content checksum for an ontology component."""

    path: str
    sha256: str


@dataclass(frozen=True)
class OntologyDiagnostic:
    """A nonfatal ontology loading issue."""

    code: str
    message: str
    path: str


@dataclass(frozen=True)
class Ontology:
    """Ontology class and property universes used to calculate coverage."""

    classes: frozenset[str]
    properties: frozenset[str]
    name: str
    class_source: OntologySource | None = None
    property_source: OntologySource | None = None
    missing_classes: bool = False
    missing_properties: bool = False
    diagnostics: tuple[OntologyDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise OntologyLoadError("ontology name must be a nonempty string")

    @property
    def fingerprint(self) -> str:
        payload = {
            "classes": sorted(self.classes),
            "properties": sorted(self.properties),
            "missing_classes": self.missing_classes,
            "missing_properties": self.missing_properties,
            "class_sha256": (
                self.class_source.sha256 if self.class_source is not None else None
            ),
            "property_sha256": (
                self.property_source.sha256
                if self.property_source is not None
                else None
            ),
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def from_sets(
        cls,
        *,
        classes: set[str] | frozenset[str],
        properties: set[str] | frozenset[str],
        name: str,
    ) -> Ontology:
        """Create an ontology from in-memory URI sets."""
        return cls(
            classes=_filter_meta(classes),
            properties=_filter_meta(properties),
            name=name,
        )

    @classmethod
    def from_directory(cls, root: str | Path, *, kg: str) -> Ontology:
        """Load class and property URI files for a named knowledge graph."""
        directory = Path(root).expanduser().resolve() / kg
        class_path = _find_file(directory, "classes.yaml", f"{kg}_classes.yaml")
        property_path = _find_file(directory, "properties.yaml", f"{kg}_props.yaml")

        diagnostics: list[OntologyDiagnostic] = []
        if class_path is None:
            logger.warning("Class ontology file not found for %r in %s", kg, directory)
            classes = frozenset[str]()
            class_source = None
            diagnostics.append(
                OntologyDiagnostic(
                    code="missing_ontology_classes",
                    message=f"class ontology file not found for {kg!r}",
                    path=str(directory),
                )
            )
        else:
            classes, class_source = _load_uri_file(class_path, "class")

        if property_path is None:
            logger.warning("Property ontology file not found for %r in %s", kg, directory)
            properties = frozenset[str]()
            property_source = None
            diagnostics.append(
                OntologyDiagnostic(
                    code="missing_ontology_properties",
                    message=f"property ontology file not found for {kg!r}",
                    path=str(directory),
                )
            )
        else:
            properties, property_source = _load_uri_file(property_path, "property")

        return cls(
            classes=classes,
            properties=properties,
            name=kg,
            class_source=class_source,
            property_source=property_source,
            missing_classes=class_path is None,
            missing_properties=property_path is None,
            diagnostics=tuple(diagnostics),
        )


def _filter_meta(uris: set[str] | frozenset[str]) -> frozenset[str]:
    invalid = next((uri for uri in uris if not isinstance(uri, str)), None)
    if invalid is not None:
        raise OntologyLoadError("ontology URIs must be strings")
    return frozenset(
        uri
        for uri in uris
        if not any(uri.startswith(prefix) for prefix in _META_PREFIXES)
    )


def _find_file(directory: Path, primary: str, legacy: str) -> Path | None:
    for filename in (primary, legacy):
        candidate = directory / filename
        if candidate.is_file():
            return candidate
    return None


def _load_uri_file(path: Path, key: str) -> tuple[frozenset[str], OntologySource]:
    raw = path.read_bytes()
    try:
        loaded: Any = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        logger.error("Malformed ontology YAML in %s", path, exc_info=True)
        raise OntologyLoadError(f"{path}: malformed YAML: {exc}") from exc
    if loaded is None:
        loaded = []
    if not isinstance(loaded, list):
        raise OntologyLoadError(f"{path}: expected a YAML sequence")

    values: set[str] = set()
    for index, item in enumerate(loaded, start=1):
        if not isinstance(item, dict):
            raise OntologyLoadError(f"{path}: item {index} must be a mapping")
        value = item.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not value:
            raise OntologyLoadError(
                f"{path}: item {index} field {key!r} must be a nonempty string"
            )
        values.add(value)

    source = OntologySource(path=str(path), sha256=hashlib.sha256(raw).hexdigest())
    return _filter_meta(values), source
