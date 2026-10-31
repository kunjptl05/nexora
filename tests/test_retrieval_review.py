import unittest
from unittest.mock import patch

from veritas_rag.conflict_radar import ConflictRadar
from veritas_rag.embeddings import EmbeddingService
from veritas_rag.models import Citation, DocumentChunk, SearchFilters
from veritas_rag.storage import StorageService


class RetrievalReviewTests(unittest.TestCase):
    def test_domain_detection_uses_token_boundaries(self):
        radar = ConflictRadar()
        self.assertEqual(
            radar._extract_domain("The author mentions PVC and a bicycle.", "General notes"),
            "general",
        )
        self.assertEqual(
            radar._extract_domain("The PV panel has a photovoltaic module.", "Solar note"),
            "solar_pv",
        )

    def test_atlas_search_filters_use_compound_filter_operators(self):
        storage = StorageService()
        clauses = storage._build_atlas_search_filters(
            SearchFilters(category="Clean Energy", min_year=2023, max_year=2025, doc_ids=["doc-a", "doc-b"])
        )
        self.assertEqual(clauses[0], {"equals": {"path": "metadata.category", "value": "Clean Energy"}})
        self.assertEqual(clauses[1], {"range": {"path": "metadata.year", "gte": 2023, "lte": 2025}})
        self.assertEqual(clauses[2], {"in": {"path": "doc_id", "value": ["doc-a", "doc-b"]}})

    def test_empty_atlas_results_retry_local_search(self):
        class ReadyCollection:
            def list_search_indexes(self):
                return [
                    {"name": "vector_index", "status": "READY"},
                    {"name": "chunk_text", "status": "READY"},
                ]

            def count_documents(self, query=None):
                return 1

            def distinct(self, field, query=None):
                return ["local-hash-projection"] if field == "embedding_model" else [128]

        storage = StorageService()
        storage.is_connected = True
        storage.collection = ReadyCollection()
        citation = Citation(
            id="chunk-a", doc_id="doc-a", doc_title="DSA notes", section="Arrays",
            page_number=1, snippet="Array indexing takes constant time for direct access.",
            similarity_score=0.8, combined_score=0.8,
        )
        with patch.object(storage, "_search_mongodb_atlas", return_value=([], [])) as atlas_search, patch.object(
            storage, "_search_local_hybrid_traced", return_value=([citation], {"pre_rrf": [], "post_rrf": []})
        ) as local_search:
            citations, trace = storage.hybrid_search("array indexing", top_k=1, search_mode="dense")

        self.assertEqual([item.id for item in citations], ["chunk-a"])
        self.assertEqual(trace["retrieval_backend"], "local_fallback")
        self.assertTrue(trace["atlas_empty_results"])
        atlas_search.assert_called_once()
        local_search.assert_called_once()

    def test_comparative_retrieval_limits_chunks_per_document_before_backfill(self):
        storage = StorageService()
        results = [
            Citation(id="a1", doc_id="doc-a", doc_title="A", section="", page_number=1, snippet="A1", similarity_score=1, combined_score=1),
            Citation(id="a2", doc_id="doc-a", doc_title="A", section="", page_number=2, snippet="A2", similarity_score=0.9, combined_score=0.9),
            Citation(id="a3", doc_id="doc-a", doc_title="A", section="", page_number=3, snippet="A3", similarity_score=0.8, combined_score=0.8),
            Citation(id="b1", doc_id="doc-b", doc_title="B", section="", page_number=1, snippet="B1", similarity_score=0.7, combined_score=0.7),
            Citation(id="b2", doc_id="doc-b", doc_title="B", section="", page_number=2, snippet="B2", similarity_score=0.6, combined_score=0.6),
        ]
        diversified = storage._diversify_results(results, 4, "Compare the two policies")
        self.assertEqual([item.id for item in diversified], ["a1", "a2", "b1", "b2"])

    def test_embedding_failure_does_not_silently_switch_vector_space(self):
        service = EmbeddingService()
        service._api_key = "configured"
        service._client = object()
        with patch.object(service, "_gemini_embed_batch", side_effect=RuntimeError("provider unavailable")):
            with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
                service.get_embedding("A retrieval query")

    def test_embedding_dimension_mismatch_is_rejected(self):
        storage = StorageService()
        storage._chunks["legacy"] = DocumentChunk(
            id="legacy",
            doc_id="legacy-doc",
            doc_title="Legacy",
            content="Some document content",
            embedding=[0.0] * 128,
            embedding_dim=128,
            embedding_model="text-embedding-004",
        )
        with patch("veritas_rag.storage.embedding_service.current_model_name", "gemini-embedding-001"):
            with self.assertRaisesRegex(RuntimeError, "different embedding space"):
                storage._validate_embedding_space([0.0] * 768)

    def test_mismatched_cosine_dimensions_raise_instead_of_returning_zero(self):
        storage = StorageService()
        with self.assertRaisesRegex(ValueError, "dimension mismatch"):
            storage._cosine_similarity([0.1] * 768, [0.1] * 128)


if __name__ == "__main__":
    unittest.main()
