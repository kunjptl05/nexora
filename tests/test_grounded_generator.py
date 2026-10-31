import unittest

from veritas_rag.generator import GroundedGenerator
from veritas_rag.models import Citation


def citation(snippet: str, page: int = 2) -> Citation:
    return Citation(
        id=f"chunk-{page}",
        doc_id="grid-storage-whitepaper",
        doc_title="Grid Storage Technical Whitepaper",
        section="Storage Overview",
        page_number=page,
        snippet=snippet,
        similarity_score=0.82,
        keyword_score=2.4,
        combined_score=0.91,
        metadata={"year": 2024},
    )


class GroundedAnswerTests(unittest.TestCase):
    def setUp(self):
        self.generator = GroundedGenerator()

    def test_battery_chemistry_is_not_misrepresented_as_physical_parts(self):
        source = (
            "Large-scale lithium iron phosphate (LFP) and sodium-ion battery "
            "chemistries serve as essential grid stabilizing assets for variable solar irradiance."
        )
        answer = self.generator._local_grounded_synthesis(
            "What are the components of the battery?", [citation(source)], []
        )

        self.assertIn("lithium iron phosphate (LFP)", answer)
        self.assertIn("sodium-ion", answer)
        self.assertIn("battery chemistries", answer)
        self.assertIn("does not provide a physical component breakdown", answer)
        self.assertIn("Verbatim evidence from your documents", answer)
        self.assertIn("Page 2", answer)
        self.assertNotIn("- **anode**", answer)
        self.assertNotIn("- **cathode**", answer)
        self.assertNotIn("- **electrolyte**", answer)

    def test_only_lists_physical_parts_that_are_in_the_passage(self):
        source = (
            "The battery cell contains an anode, a cathode, an electrolyte, "
            "and a porous separator."
        )
        answer = self.generator._local_grounded_synthesis(
            "What are the components of the battery?", [citation(source)], []
        )

        self.assertIn("Physical battery components explicitly named", answer)
        self.assertIn("**anode**", answer)
        self.assertIn("**cathode**", answer)
        self.assertIn("**electrolyte**", answer)
        self.assertIn("**separator**", answer)

    def test_does_not_invent_components_when_passage_has_no_component_list(self):
        source = "Battery storage systems support renewable energy integration and grid stability."
        answer = self.generator._local_grounded_synthesis(
            "List the internal components of this battery.", [citation(source)], []
        )

        self.assertIn("do not provide a clear list", answer)
        self.assertIn("not stated in the retrieved evidence", answer)
        self.assertNotIn("anode", answer)
        self.assertNotIn("cathode", answer)
        self.assertNotIn("electrolyte", answer)

    def test_exact_mode_returns_the_original_sentence_and_source(self):
        source = (
            "Large-scale lithium iron phosphate (LFP) and sodium-ion battery "
            "chemistries serve as essential grid stabilizing assets for variable solar irradiance."
        )
        answer = self.generator._exact_extraction_answer(
            "Which battery chemistries are named?", [citation(source, page=4)]
        )

        self.assertIn(source, answer)
        self.assertIn("Grid Storage Technical Whitepaper", answer)
        self.assertIn("Page 4", answer)

    def test_component_prompt_requires_a_complete_supported_list(self):
        prompt = self.generator._build_grounded_prompt(
            "What are the components of the battery?", [citation("LFP and sodium-ion battery chemistries.")], []
        )
        self.assertIn("Enumerate every distinct item explicitly named", prompt)
        self.assertIn("not internal cell components", prompt)
        self.assertIn("Do not supply a generic textbook list", prompt)


if __name__ == "__main__":
    unittest.main()
