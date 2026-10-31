import unittest

from veritas_rag.field_extractor import detect_field_intent, extract_labelled_fields
from veritas_rag.models import Citation, SearchFilters
from veritas_rag.storage import StorageService
from veritas_rag.generator import GroundedGenerator


FORM_TEXT = """[Page 1]
Mukhyamantri Yuva Swavalamban Yojana
Candidate Details :
Name : SAMPLE STUDENT ID:STU12345
Date of Birth : 12-03-2005 Aadhaar card number: ********1234 Category : General
E-mail : sample@example.com Mobile No : 9000000000
Bank Name : SAMPLE BANK
Bank Branch : MAIN BRANCH
Family Annual Income (Rs.) : 220000
[Page 2]
Admission Details :
University : SAMPLE UNIVERSITY Programme : BACHELOR OF TECHNOLOGY
"""


class FieldIntentTests(unittest.TestCase):
    def test_person_name_questions_map_to_candidate_name(self):
        questions = [
            "What is the name of the person in this document?",
            "Who is the applicant?",
            "What is the candidate name?",
        ]
        for question in questions:
            with self.subTest(question=question):
                self.assertEqual(detect_field_intent(question), "candidate_name")

    def test_component_questions_are_not_mistaken_for_name_lookup(self):
        self.assertIsNone(detect_field_intent("What are the components of the battery?"))

    def test_extracts_candidate_name_and_adjacent_id_exactly(self):
        fields = extract_labelled_fields(FORM_TEXT)
        name = next(item for item in fields if item["field_key"] == "candidate_name")
        record_id = next(item for item in fields if item["field_key"] == "record_id")

        self.assertEqual(name["value"], "SAMPLE STUDENT")
        self.assertEqual(name["page_number"], 1)
        self.assertEqual(record_id["value"], "STU12345")
        self.assertIn("Name: SAMPLE STUDENT", name["source_line"])

    def test_bank_name_is_not_mistaken_for_candidate_name(self):
        fields = extract_labelled_fields(FORM_TEXT)
        candidate_names = [item["value"] for item in fields if item["field_key"] == "candidate_name"]
        bank_names = [item["value"] for item in fields if item["field_key"] == "bank_name"]

        self.assertEqual(candidate_names, ["SAMPLE STUDENT"])
        self.assertEqual(bank_names, ["SAMPLE BANK"])

    def test_adjacent_fields_with_parenthesized_units_and_page_markers(self):
        fields = extract_labelled_fields(FORM_TEXT)
        income = next(item for item in fields if item["field_key"] == "family_income")
        university = next(item for item in fields if item["field_key"] == "university")

        self.assertEqual(income["value"], "220000")
        self.assertEqual(income["page_number"], 1)
        self.assertEqual(university["value"], "SAMPLE UNIVERSITY")
        self.assertEqual(university["page_number"], 2)

    def test_field_search_respects_selected_document_scope(self):
        storage = StorageService()
        storage.add_document("doc_a", "Form A", {"category": "General"}, FORM_TEXT)
        storage.add_document("doc_b", "Form B", {"category": "General"}, FORM_TEXT.replace("SAMPLE STUDENT", "OTHER STUDENT"))

        matches = storage.search_labelled_fields(
            "candidate_name",
            SearchFilters(doc_ids=["doc_b"])
        )
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["value"], "OTHER STUDENT")

    def test_field_answer_contains_exact_value_and_page_citation(self):
        storage = StorageService()
        storage.add_document("doc_a", "Form A", {"category": "General"}, FORM_TEXT)
        matches = storage.search_labelled_fields("candidate_name")
        response = GroundedGenerator().generate_field_response(
            "What is the name of the person in this document?",
            matches,
            {"retrieval_mode": "structured_field_lookup"}
        )
        self.assertIn("SAMPLE STUDENT", response.answer)
        self.assertIn("Form A", response.answer)
        self.assertIn("p.1", response.answer)
        self.assertEqual(response.generation_mode, "structured-field-extraction")


if __name__ == "__main__":
    unittest.main()
