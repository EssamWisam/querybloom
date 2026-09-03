"""Deterministic prefix extraction and CURIE formatting for RDF IRIs."""

from __future__ import annotations

from collections.abc import Iterable
import re
from urllib.parse import urlsplit


_SAFE_LOCAL_NAME = re.compile(
    r"[A-Za-z_0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9_-])?\Z"
)


class PrefixExtractor:
    """Build deterministic prefix aliases for a closed collection of IRIs."""

    def __init__(self, uris: Iterable[str]):
        self._uris = tuple(sorted(set(uris)))
        split_uris = {
            uri: parts
            for uri in self._uris
            if (parts := self._split_uri(uri)) is not None
        }
        namespaces = sorted({namespace for namespace, _ in split_uris.values()})
        self._namespace_to_prefix = self._assign_prefixes(namespaces)
        self._prefix_to_namespace = {
            prefix: namespace
            for namespace, prefix in self._namespace_to_prefix.items()
        }
        self._uri_map = {
            uri: self._compress_parts(uri, split_uris.get(uri))
            for uri in self._uris
        }

    @property
    def prefixes(self) -> dict[str, str]:
        """Return ``{prefix: namespace}`` for direct YAML serialization."""
        return dict(self._prefix_to_namespace)

    @property
    def uri_map(self) -> dict[str, str]:
        """Return ``{original IRI: CURIE or <full-iri>}`` for all input IRIs."""
        return dict(self._uri_map)

    def compress(self, uri: str) -> str:
        """Return a CURIE when safe, otherwise return the full bracketed IRI."""
        if uri in self._uri_map:
            return self._uri_map[uri]
        return self._compress_parts(uri, self._split_uri(uri))

    def expand(self, value: str) -> str:
        """Expand a generated CURIE or bracketed IRI back to its original IRI."""
        if value.startswith("<") and value.endswith(">"):
            return value[1:-1]
        prefix, separator, local_name = value.partition(":")
        if not separator or prefix not in self._prefix_to_namespace:
            raise ValueError(f"Unknown prefixed IRI: {value}")
        return f"{self._prefix_to_namespace[prefix]}{local_name}"

    def _compress_parts(
        self, uri: str, parts: tuple[str, str] | None
    ) -> str:
        if parts is None:
            return f"<{uri}>"
        namespace, local_name = parts
        prefix = self._namespace_to_prefix.get(namespace)
        if prefix is None:
            return f"<{uri}>"
        return f"{prefix}:{local_name}"

    @staticmethod
    def _split_uri(uri: str) -> tuple[str, str] | None:
        if not isinstance(uri, str) or not uri:
            return None

        fragment_index = uri.rfind("#")
        if fragment_index >= 0:
            candidate = (uri[: fragment_index + 1], uri[fragment_index + 1 :])
            if PrefixExtractor._safe_candidate(candidate):
                return candidate

        parsed = urlsplit(uri)
        if parsed.scheme in {"http", "https"}:
            path_index = uri.rfind("/")
            authority_end = uri.find("/", uri.find(":") + 3)
            if authority_end >= 0 and path_index >= authority_end:
                candidate = (uri[: path_index + 1], uri[path_index + 1 :])
                if PrefixExtractor._safe_candidate(candidate):
                    return candidate
            return None

        colon_index = uri.rfind(":")
        if colon_index > uri.find(":"):
            candidate = (uri[: colon_index + 1], uri[colon_index + 1 :])
            if PrefixExtractor._safe_candidate(candidate):
                return candidate
        return None

    @staticmethod
    def _safe_candidate(candidate: tuple[str, str]) -> bool:
        namespace, local_name = candidate
        return bool(namespace and _SAFE_LOCAL_NAME.fullmatch(local_name))

    @staticmethod
    def _assign_prefixes(namespaces: list[str]) -> dict[str, str]:
        assigned: dict[str, str] = {}
        used: set[str] = set()
        for namespace in namespaces:
            base = PrefixExtractor._prefix_name(namespace)
            prefix = base
            suffix = 2
            while prefix in used:
                prefix = f"{base}{suffix}"
                suffix += 1
            assigned[namespace] = prefix
            used.add(prefix)
        return assigned

    @staticmethod
    def _prefix_name(namespace: str) -> str:
        parsed = urlsplit(namespace)
        if parsed.scheme in {"http", "https"}:
            name_source = f"{parsed.netloc}{parsed.path}"
        else:
            name_source = namespace

        parts = re.findall(r"[A-Za-z0-9]+", name_source)
        letters = [next((char.lower() for char in part if char.isalpha()), "") for part in parts]
        prefix = "".join(letters) or "ns"
        if not prefix[0].isalpha():
            prefix = f"ns{prefix}"
        return prefix