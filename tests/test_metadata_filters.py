import unittest

from veritas_rag.config import config
from veritas_rag.models import DocumentChunk, SearchFilters
from veritas_rag.storage import StorageService


class MetadataFilterTests(unittest.TestCase):
    def setUp(self):
        self.storage = StorageService()
        self.previous_owner = config.owner_id
        config.owner_id = "owner-a"
        self.chunk = DocumentChunk(
            doc_id="doc-a", doc_title="Notes", content="A study passage",
            metadata={"owner_id": "owner-a", "content_type": "application/pdf", "uploaded_at": 1000, "category": "Course"},
        )

    def tearDown(self):
        config.owner_id = self.previous_owner

    def test_owner_scope_is_always_server_derived(self):
        filters = SearchFilters(owner_id="owner-b")
        self.assertEqual(self.storage._build_mongo_filter(filters)["metadata.owner_id"], "owner-a")
        self.assertTrue(self.storage._matches_filter(self.chunk, filters))
        other_owner_chunk = self.chunk.model_copy(update={"metadata": {**self.chunk.metadata, "owner_id": "owner-b"}})
        self.assertFalse(self.storage._matches_filter(other_owner_chunk, None))

    def test_upload_date_and_content_type_filters(self):
        self.assertTrue(self.storage._matches_filter(self.chunk, SearchFilters(upload_after=999, upload_before=1001, content_type="application/pdf")))
        self.assertFalse(self.storage._matches_filter(self.chunk, SearchFilters(upload_after=1001)))
        self.assertFalse(self.storage._matches_filter(self.chunk, SearchFilters(content_type="text/plain")))

    def test_atlas_vector_and_search_filter_keep_owner_scope(self):
        filters = SearchFilters(content_type="application/pdf", upload_after=900)
        mongo = self.storage._build_mongo_filter(filters)
        atlas = self.storage._build_atlas_search_filters(filters)
        self.assertEqual(mongo["metadata.owner_id"], "owner-a")
        self.assertIn({"equals": {"path": "metadata.owner_id", "value": "owner-a"}}, atlas)
        self.assertEqual(mongo["metadata.content_type"], "application/pdf")
        self.assertIn({"range": {"path": "metadata.uploaded_at", "gte": 900}}, atlas)


if __name__ == "__main__":
    unittest.main()
