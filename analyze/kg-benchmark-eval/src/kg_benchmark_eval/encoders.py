"""Embedding encoder interfaces and implementations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from types import MappingProxyType
from typing import Protocol

import numpy as np
import numpy.typing as npt

BGE_PROMPT = "Represent this sentence: "


@dataclass(frozen=True)
class EncoderIdentity:
    model_id: str
    revision: str
    prompt: str
    normalize_embeddings: bool
    max_sequence_length: int | None
    dtype: str
    device: str
    backend: str
    library_versions: tuple[tuple[str, str], ...]
    content_fingerprint: str | None = None

    def to_dict(self) -> Mapping[str, object]:
        return MappingProxyType(asdict(self))


class EmbeddingEncoder(Protocol):
    @property
    def identity(self) -> EncoderIdentity: ...

    def encode(self, questions: tuple[str, ...]) -> npt.NDArray[np.floating]: ...


class SentenceTransformerEncoder:
    def __init__(
        self,
        *,
        model_id: str,
        revision: str,
        device: str = "cpu",
        max_sequence_length: int | None = None,
        dtype: str = "float32",
    ) -> None:
        if not model_id.strip() or not revision.strip():
            raise ValueError("model_id and revision must be nonempty strings")
        self.model_id = model_id
        self.revision = revision
        self.device = device
        self.max_sequence_length = max_sequence_length
        self.dtype = dtype
        self._model: object | None = None
        prompt = BGE_PROMPT if "bge" in model_id.lower() else ""
        self._identity = EncoderIdentity(
            model_id=model_id,
            revision=revision,
            prompt=prompt,
            normalize_embeddings=True,
            max_sequence_length=max_sequence_length,
            dtype=dtype,
            device=device,
            backend="sentence-transformers",
            library_versions=tuple(
                (package, _package_version(package))
                for package in (
                    "sentence-transformers",
                    "transformers",
                    "torch",
                    "numpy",
                )
            ),
        )

    @property
    def identity(self) -> EncoderIdentity:
        return self._identity

    def encode(self, questions: tuple[str, ...]) -> npt.NDArray[np.floating]:
        model = self._load_model()
        prompt = self.identity.prompt
        inputs = tuple(
            question if not prompt or question.startswith(prompt) else prompt + question
            for question in questions
        )
        raw = model.encode(  # type: ignore[attr-defined]
            list(inputs), normalize_embeddings=True
        )
        matrix = np.asarray(raw, dtype=np.dtype(self.dtype))
        return validate_embeddings(matrix, len(questions))

    def _load_model(self) -> object:
        if self._model is None:
            try:
                sentence_transformers = import_module("sentence_transformers")
            except ImportError as exc:
                raise ImportError(
                    "semantic evaluation requires kg-benchmark-eval[semantic]"
                ) from exc
            model = sentence_transformers.SentenceTransformer(
                self.model_id, revision=self.revision, device=self.device
            )
            if self.max_sequence_length is not None:
                model.max_seq_length = self.max_sequence_length
            self._model = model
        return self._model


class FrozenEncoder:
    """Deterministic encoder for offline evaluations and tests."""

    def __init__(
        self,
        embeddings: npt.NDArray[np.floating],
        *,
        fingerprint: str,
    ) -> None:
        matrix = np.asarray(embeddings)
        self._embeddings = validate_embeddings(matrix, len(matrix))
        self._identity = EncoderIdentity(
            model_id="frozen",
            revision=fingerprint,
            prompt="",
            normalize_embeddings=True,
            max_sequence_length=None,
            dtype=str(matrix.dtype),
            device="offline",
            backend="frozen",
            library_versions=(("numpy", np.__version__),),
            content_fingerprint=fingerprint,
        )

    @property
    def identity(self) -> EncoderIdentity:
        return self._identity

    def encode(self, questions: tuple[str, ...]) -> npt.NDArray[np.floating]:
        if len(questions) != len(self._embeddings):
            raise ValueError("frozen embedding row count does not match questions")
        result = self._embeddings.copy()
        result.setflags(write=False)
        return result


def validate_embeddings(
    embeddings: npt.NDArray[np.floating], expected_rows: int
) -> npt.NDArray[np.floating]:
    if embeddings.ndim != 2 or embeddings.shape[0] != expected_rows:
        raise ValueError("encoder returned an embedding matrix with the wrong shape")
    if not np.isfinite(embeddings).all():
        raise ValueError("encoder returned nonfinite embeddings")
    if expected_rows and not np.allclose(
        np.linalg.norm(embeddings, axis=1), 1.0, rtol=1e-6, atol=1e-8
    ):
        raise ValueError("encoder must return L2-normalized embeddings")
    embeddings.setflags(write=False)
    return embeddings


def _package_version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "not-installed"
