"""Small Okapi BM25 implementation retaining BizInsight Chinese n-grams."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Sequence
from typing import Any


class BM25Index:
    def __init__(
        self,
        documents: Sequence[dict[str, Any]],
        *,
        tokenizer: Callable[[str], list[str]],
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.documents = list(documents)
        self.tokenizer = tokenizer
        self.k1 = k1
        self.b = b
        self.terms = [Counter(tokenizer(str(item["content"]))) for item in documents]
        self.lengths = [sum(item.values()) for item in self.terms]
        self.average_length = sum(self.lengths) / max(len(self.lengths), 1)
        self.document_frequency = Counter(
            term for terms in self.terms for term in terms
        )

    def search(
        self, query: str, *, top_k: int = 5
    ) -> list[tuple[float, dict[str, Any]]]:
        query_terms = self.tokenizer(query)
        count = len(self.documents)
        ranked: list[tuple[float, dict[str, Any]]] = []
        for document, frequencies, length in zip(
            self.documents, self.terms, self.lengths, strict=True
        ):
            score = 0.0
            for term in query_terms:
                frequency = frequencies[term]
                if not frequency:
                    continue
                df = self.document_frequency[term]
                idf = math.log(1 + (count - df + 0.5) / (df + 0.5))
                norm = frequency + self.k1 * (
                    1 - self.b + self.b * length / max(self.average_length, 1)
                )
                score += idf * frequency * (self.k1 + 1) / norm
            if score:
                ranked.append((score, document))
        ranked.sort(key=lambda item: (-item[0], str(item[1].get("chunk_id", ""))))
        return ranked[:top_k]
