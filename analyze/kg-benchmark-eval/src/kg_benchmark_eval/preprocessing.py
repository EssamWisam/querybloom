"""Normalize, parse, and derive structural features from SPARQL queries."""

from __future__ import annotations

import logging
import re
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from rdflib.plugins.sparql.algebra import translateQuery
from rdflib.plugins.sparql.parser import parseQuery
from rdflib.term import Literal as RDFLiteral
from rdflib.term import URIRef, Variable

from .benchmark import NormalizationProfile

logger = logging.getLogger(__name__)

FEATURE_KEYS = (
    "SELECT",
    "ASK",
    "DISTINCT",
    "COUNT",
    "OPTIONAL",
    "UNION",
    "FILTER",
    "EXISTS",
    "GROUP BY",
    "HAVING",
    "ORDER BY",
    "LIMIT",
    "Property Paths",
)

_QALD9_PREFIXES = {
    "dbc": "http://dbpedia.org/resource/Category:",
    "dct": "http://purl.org/dc/terms/",
    "yago": "http://dbpedia.org/class/yago/",
}

_LITERAL_PATTERN = re.compile(
    r"""
    (?:
        "(?:\\.|[^"\\])*"
        | '(?:\\.|[^'\\])*'
    )
    (?:
        @[a-zA-Z]+(?:-[a-zA-Z0-9]+)*
        | \^\^<URI>
    )?
    |
    (?<![a-zA-Z0-9_.])
    [+-]?
    (?:\d+\.\d*|\.\d+|\d+)
    (?:[eE][+-]?\d+)?
    (?![a-zA-Z0-9_.])
    """,
    re.VERBOSE,
)

_SPARQL_BUILTIN_FUNCS = {
    "REGEX",
    "CONTAINS",
    "STRSTARTS",
    "STRENDS",
    "STRLEN",
    "SUBSTR",
    "UCASE",
    "LCASE",
    "ENCODE_FOR_URI",
    "CONCAT",
    "REPLACE",
    "YEAR",
    "MONTH",
    "DAY",
    "HOURS",
    "MINUTES",
    "SECONDS",
    "TIMEZONE",
    "TZ",
    "NOW",
    "LANG",
    "LANGMATCHES",
    "DATATYPE",
    "BOUND",
    "SAMETERM",
    "ISIRI",
    "ISURI",
    "ISBLANK",
    "ISLITERAL",
    "ISNUMERIC",
    "ABS",
    "ROUND",
    "CEIL",
    "FLOOR",
    "RAND",
    "IF",
    "COALESCE",
    "IN",
    "BNODE",
    "STRDT",
    "STRLANG",
    "STR",
    "IRI",
    "URI",
}
_NESTED_HELPERS = {"NOW", "STR", "URI", "IRI", "BNODE"}


@dataclass(frozen=True)
class ParsedQuery:
    """Structural facts extracted from a SPARQL query or its parse failure."""

    num_triples: int
    variables: frozenset[str]
    raw_entities: tuple[str, ...]
    literals: tuple[str, ...]
    syntactic_classes: frozenset[str]
    properties: frozenset[str]
    parse_status: Literal["ok", "failed"]
    error: str | None = None


@dataclass(frozen=True)
class TextAnalysis:
    """Text-derived query features and anonymized templates."""

    features: Mapping[str, int]
    template: str
    filter_templates: tuple[str, ...]
    filter_subtypes: frozenset[str]


def normalize_sparql(sparql: str, *, profile: NormalizationProfile = "standard") -> str:
    normalized = _normalize_uri_escapes(sparql)
    normalized = re.sub(
        r"""(?<!\\)(["'])\s+(@[A-Za-z]+(?:-[A-Za-z0-9]+)*\b)""",
        r"\1\2",
        normalized,
    )
    normalized = re.sub(r"""(?<!\\)(["'])\s*\^\^\s*""", r"\1^^", normalized)

    if profile == "qald9":
        declared = set(re.findall(r"(?i)\bPREFIX\s+([A-Za-z][\w-]*):", normalized))
        used = set(re.findall(r"(?<![<\w])([A-Za-z][\w-]*):[A-Za-z_]", normalized))
        additions = [
            f"PREFIX {prefix}: <{namespace}>"
            for prefix, namespace in _QALD9_PREFIXES.items()
            if prefix in used - declared
        ]
        if additions:
            normalized = " ".join(additions + [normalized])
    elif profile != "standard":
        raise ValueError(f"unknown normalization profile: {profile!r}")
    return normalized


def get_query_body(sparql: str) -> str:
    return re.sub(
        r"^\s*(?:PREFIX\s+(?:[a-zA-Z][a-zA-Z0-9_-]*)?:\s*<[^>]+>\s*)+",
        "",
        sparql,
        flags=re.IGNORECASE,
    ).strip()


def strip_lang_en_filters(sparql: str) -> str:
    result = re.sub(
        r"""\bFILTER\s*\(\s*
            lang\s*\(
            [^)]*
            \)\s*=\s*
            ['"]en['"]\s*
            \)
        """,
        "",
        sparql,
        flags=re.IGNORECASE | re.VERBOSE,
    )
    return re.sub(
        r"""\bFILTER\s*\(\s*
            langMatches\s*\(\s*
            lang\s*\(
            [^)]*
            \)\s*,\s*
            ['"]en['"]\s*
            \)\s*
            \)
        """,
        "",
        result,
        flags=re.IGNORECASE | re.VERBOSE,
    )


def analyze_sparql_features(sparql: str) -> Mapping[str, int]:
    upper_sparql = sparql.upper()
    body = strip_lang_en_filters(get_query_body(sparql))
    upper_body = body.upper()
    sanitized = re.sub(r"<[^>]+>", "URI", body)
    sanitized = re.sub(r'".*?"(\^\^<.*?>)?', "LITERAL", sanitized)
    values = {
        "SELECT": int(bool(re.search(r"\bSELECT\b", upper_sparql))),
        "ASK": int(bool(re.search(r"\bASK\b", upper_sparql))),
        "DISTINCT": int(bool(re.search(r"\bDISTINCT\b", upper_sparql))),
        "COUNT": int(bool(re.search(r"\bCOUNT\b", upper_sparql))),
        "OPTIONAL": int("OPTIONAL" in upper_body),
        "UNION": int("UNION" in upper_body),
        "FILTER": int("FILTER" in upper_body),
        "EXISTS": int(bool(re.search(r"\bEXISTS\b", upper_body))),
        "GROUP BY": int("GROUP BY" in upper_body),
        "HAVING": int("HAVING" in upper_body),
        "ORDER BY": int("ORDER BY" in upper_body),
        "LIMIT": int("LIMIT" in upper_body),
        "Property Paths": int(
            bool(re.search(r"(:[a-zA-Z0-9_]+|URI)[\s]*[\*\+\|/]", sanitized))
        ),
    }
    return MappingProxyType(values)


def analyze_text(sparql: str) -> TextAnalysis:
    return TextAnalysis(
        features=analyze_sparql_features(sparql),
        template=anonymise_query(sparql),
        filter_templates=extract_filter_templates(sparql),
        filter_subtypes=extract_filter_subtypes(sparql),
    )


def parse_sparql(sparql: str) -> ParsedQuery:
    """Parse a query, returning an explicit failed result when parsing fails."""
    num_triples = 0
    variables: set[str] = set()
    entities: list[str] = []
    literals: list[str] = []
    classes: set[str] = set()
    properties: set[str] = set()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            algebra = translateQuery(parseQuery(sparql)).algebra
    except Exception as exc:  # noqa: BLE001 - parse failures are data outcomes
        logger.warning("SPARQL parsing failed; using empty structural terms", exc_info=True)
        return ParsedQuery(
            num_triples=0,
            variables=frozenset(),
            raw_entities=(),
            literals=(),
            syntactic_classes=frozenset(),
            properties=frozenset(),
            parse_status="failed",
            error=str(exc),
        )

    def walk_algebra(node: object) -> None:
        nonlocal num_triples
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "triples" and value is not None:
                    triples = list(value)
                    num_triples += len(triples)
                    for triple in triples:
                        subject, predicate, obj = triple[:3]
                        is_type_triple = (
                            str(predicate)
                            == "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
                            and isinstance(obj, URIRef)
                        )
                        if is_type_triple:
                            classes.add(str(obj))
                        for term, is_class_object in (
                            (subject, False),
                            (obj, is_type_triple),
                        ):
                            if is_class_object:
                                continue
                            if isinstance(term, URIRef):
                                entities.append(str(term))
                            elif isinstance(term, RDFLiteral):
                                literals.append(str(term))
                            elif isinstance(term, Variable):
                                variables.add(str(term))
                        if isinstance(predicate, URIRef):
                            properties.add(str(predicate))
                        elif isinstance(predicate, Variable):
                            variables.add(str(predicate))
                else:
                    walk_algebra(value)
        elif isinstance(node, list):
            for item in node:
                walk_algebra(item)

    walk_algebra(algebra)
    projection = getattr(algebra, "PV", None)
    if projection is not None:
        variables.clear()
        variables.update(str(variable) for variable in projection)
    return ParsedQuery(
        num_triples=num_triples,
        variables=frozenset(variables),
        raw_entities=tuple(str(value) for value in entities),
        literals=tuple(str(value) for value in literals),
        syntactic_classes=frozenset(str(value) for value in classes),
        properties=frozenset(str(value) for value in properties),
        parse_status="ok",
    )


def anonymise_query(sparql: str) -> str:
    return _anonymise_fragment(get_query_body(sparql))


def extract_filter_templates(sparql: str) -> tuple[str, ...]:
    body = strip_lang_en_filters(get_query_body(sparql))
    upper = body.upper()
    if "FILTER" not in upper:
        return ()
    templates: list[str] = []
    templates.extend(
        "FILTER NOT EXISTS { ... }"
        for _ in re.finditer(r"\bFILTER\s+NOT\s+EXISTS\b", upper)
    )
    templates.extend(
        "FILTER EXISTS { ... }"
        for _ in re.finditer(r"\bFILTER\s+(?!NOT)EXISTS\b", upper)
    )
    for match in re.finditer(r"\bFILTER\s*\(", body, re.IGNORECASE):
        clause, _ = _balanced_fragment(body, match.end(), "(", ")")
        templates.append(
            "FILTER ( " + _anonymise_fragment(clause, collapse_whitespace=True) + " )"
        )
    return tuple(templates)


def extract_filter_subtypes(sparql: str) -> frozenset[str]:
    body = strip_lang_en_filters(get_query_body(sparql))
    upper = body.upper()
    if "FILTER" not in upper:
        return frozenset()
    subtypes: set[str] = set()
    if re.search(r"\bFILTER\s+NOT\s+EXISTS\b", upper):
        subtypes.add("FILTER:NOT EXISTS")
    if re.search(r"\bFILTER\s+(?!NOT)EXISTS\b", upper):
        subtypes.add("FILTER:EXISTS")
    for match in re.finditer(r"\bFILTER\s*\(", upper):
        clause, _ = _balanced_fragment(upper, match.end(), "(", ")")
        functions = [
            token
            for token in re.findall(r"\b([A-Z_]+)\s*\(", clause)
            if token in _SPARQL_BUILTIN_FUNCS
        ]
        informative = [name for name in functions if name not in _NESTED_HELPERS]
        labels = informative if informative else functions
        if labels:
            subtypes.add(f"FILTER:{labels[0]}")
        elif "!=" in clause:
            subtypes.add("FILTER:!=")
        elif re.search(r">=|<=|(?<!=)>|(?<!=)<(?!=)", clause):
            subtypes.add("FILTER:comparison")
        elif "=" in clause:
            subtypes.add("FILTER:=")
        elif re.search(r"\bIN\b", clause):
            subtypes.add("FILTER:IN")
        else:
            subtypes.add("FILTER:other")
    return frozenset(subtypes)


class QueryPreprocessor:
    """Run-local deduplication for deterministic preprocessing artifacts."""

    def __init__(self) -> None:
        self._normalized: dict[tuple[str, NormalizationProfile], str] = {}
        self._parsed: dict[str, ParsedQuery] = {}
        self._text: dict[str, TextAnalysis] = {}

    def normalize(self, sparql: str, profile: NormalizationProfile) -> str:
        key = (sparql, profile)
        if key not in self._normalized:
            self._normalized[key] = normalize_sparql(sparql, profile=profile)
        return self._normalized[key]

    def parse(self, sparql: str) -> ParsedQuery:
        if sparql not in self._parsed:
            self._parsed[sparql] = parse_sparql(sparql)
        return self._parsed[sparql]

    def analyze(self, sparql: str) -> TextAnalysis:
        if sparql not in self._text:
            self._text[sparql] = analyze_text(sparql)
        return self._text[sparql]


def _normalize_uri_escapes(sparql: str) -> str:
    return re.sub(
        r"<([^>]*)>",
        lambda match: (
            "<" + re.sub(r"\\([!'()*+,;=:/?#@$_\-.~])", r"\1", match.group(1)) + ">"
        ),
        sparql,
    )


def _anonymise_fragment(text: str, *, collapse_whitespace: bool = False) -> str:
    anonymised = re.sub(r"\?[a-zA-Z0-9_]+", "?VAR", text)
    anonymised = re.sub(r"<[^>]+>", "<URI>", anonymised)
    anonymised = _LITERAL_PATTERN.sub("<LITERAL>", anonymised)
    anonymised = re.sub(r"\b[a-zA-Z0-9_]+:[a-zA-Z0-9_]+\b", "<URI>", anonymised)
    if collapse_whitespace:
        anonymised = re.sub(r"\s+", " ", anonymised)
    return anonymised.strip()


def _balanced_fragment(
    text: str, start: int, opening: str, closing: str
) -> tuple[str, int]:
    depth = 1
    position = start
    while position < len(text) and depth > 0:
        if text[position] == opening:
            depth += 1
        elif text[position] == closing:
            depth -= 1
        position += 1
    return text[start : position - 1], position
