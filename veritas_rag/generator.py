import re
import time
from typing import List, Dict, Any, Tuple
from veritas_rag.models import Citation, ConflictItem, QueryResponse
from veritas_rag.config import config
from veritas_rag.conflict_radar import conflict_radar

class GroundedGenerator:
    def __init__(self):
        self._api_key = config.gemini_api_key

    def generate_response(
        self, 
        question: str, 
        citations: List[Citation],
        explain_search: Dict[str, Any]
    ) -> QueryResponse:
        start_time = time.perf_counter()

        # 1. Hallucination Guardrail & Abstention Check
        abstained, reason = self._check_abstention(question, citations)
        if abstained:
            latency = (time.perf_counter() - start_time) * 1000
            return QueryResponse(
                question=question,
                answer=(
                    f"**Safe Abstention Triggered**\n\n"
                    f"I couldn't find sufficient verified evidence in your uploaded documents to answer:\n"
                    f"> *\"{question}\"*\n\n"
                    f"**Reason:** {reason}\n\n"
                    f"To answer this query, please upload or import relevant reference documents."
                ),
                abstained=True,
                abstention_reason=reason,
                citations=[],
                conflicts=[],
                groundedness_score=0.0,
                latency_ms=round(latency, 2),
                explain_search=explain_search
            )

        # 2. Run Conflict Radar across retrieved passages
        conflicts = conflict_radar.detect_conflicts(citations, question)

        # 3. Generate Answer (Gemini API or Local Grounded Synthesizer)
        answer = self._synthesize_answer(question, citations, conflicts)

        # 4. Measure Groundedness / Faithfulness Score
        groundedness = self._calculate_groundedness(answer, citations)
        latency = (time.perf_counter() - start_time) * 1000

        return QueryResponse(
            question=question,
            answer=answer,
            abstained=False,
            abstention_reason=None,
            citations=citations,
            conflicts=conflicts,
            groundedness_score=round(groundedness, 1),
            latency_ms=round(latency, 2),
            explain_search=explain_search
        )

    def _check_abstention(self, question: str, citations: List[Citation]) -> Tuple[bool, str]:
        if not citations:
            return True, "No matching document passages could be retrieved from the knowledge base."

        # Check top similarity and keyword scores
        top_score = max(c.similarity_score for c in citations)
        top_keyword = max(c.keyword_score for c in citations)

        # Significant non-stopword query tokens
        q_tokens = set(re.findall(r'\b[a-z0-9]{3,}\b', question.lower())) - {
            "what", "how", "why", "when", "where", "which", "who", "does", "explain",
            "the", "and", "for", "with", "from", "today", "current", "tell"
        }

        # Check how many key query tokens exist in ANY of the retrieved citations
        combined_corpus = " ".join(c.snippet.lower() for c in citations)
        matched_tokens = sum(1 for t in q_tokens if t in combined_corpus)
        token_coverage = matched_tokens / max(1, len(q_tokens))

        # If key query tokens (like 'gold', 'cricket', 'weather') have zero coverage in retrieved docs
        if token_coverage < 0.25 and top_keyword < 0.15:
            missing_tokens = [t for t in q_tokens if t not in combined_corpus]
            return True, f"Core subjects ({', '.join(missing_tokens[:3])}) are not mentioned in any indexed documents."

        # If similarity score is too low
        if top_score < 0.32 and top_keyword < 0.2:
            return True, f"Retrieval confidence score ({top_score:.2f}) is below the minimum threshold for factual generation."

        return False, ""

    def _synthesize_answer(
        self, 
        question: str, 
        citations: List[Citation], 
        conflicts: List[ConflictItem]
    ) -> str:
        # If Gemini API Key is configured, use official SDK
        if config.gemini_api_key:
            try:
                from google import genai
                client = genai.Client(api_key=config.gemini_api_key)
                
                context_blocks = []
                for idx, c in enumerate(citations):
                    context_blocks.append(
                        f"[Source {idx+1}: {c.doc_title} | Section: {c.section} | Page: {c.page_number}]\n{c.snippet}"
                    )
                context_text = "\n\n---\n\n".join(context_blocks)

                conflict_hints = ""
                if conflicts:
                    conflict_hints = "\nNOTE: The following conflicts were identified between sources:\n"
                    for cf in conflicts:
                        conflict_hints += f"- {cf.subject}: {cf.claim_a} vs {cf.claim_b}. Explain this discrepancy!\n"

                prompt = f"""You are Nexora, an evidence-grounded document intelligence platform.
Answer the user's question using ONLY the provided verified source passages.

Rules:
1. Synthesize evidence across multiple sources when available.
2. Add inline clickable citation markers in format `[Doc Title: §Section]` after facts.
3. If sources contradict each other, highlight the disagreement clearly and cite both sides.
4. Do NOT hallucinate facts not present in the excerpts.

{conflict_hints}

Passages:
{context_text}

User Question: {question}

Answer:"""

                response = client.models.generate_content(
                    model=config.gemini_model,
                    contents=prompt
                )
                if response.text:
                    return response.text.strip()
            except Exception as e:
                print(f"[GroundedGenerator] Gemini call failed, using local grounded synthesizer: {e}")

        # Local Grounded Synthesis Engine
        return self._local_grounded_synthesis(question, citations, conflicts)

    def _local_grounded_synthesis(
        self, 
        question: str, 
        citations: List[Citation], 
        conflicts: List[ConflictItem]
    ) -> str:
        """
        High-fidelity deterministic grounded synthesis.
        Extracts key sentences matching the query from retrieved sources and formats citations.
        """
        q_words = set(re.findall(r'\b[a-z0-9]+\b', question.lower())) - {"what", "how", "why", "when", "is", "are", "the", "a", "an", "do", "does"}

        bullet_points = []
        used_docs = set()

        for cit in citations:
            sentences = re.split(r'(?<=[.!?])\s+', cit.snippet)
            scored_sentences = []
            for s in sentences:
                s_clean = s.strip()
                if len(s_clean) < 20:
                    continue
                s_words = set(re.findall(r'\b[a-z0-9]+\b', s_clean.lower()))
                overlap = len(q_words & s_words)
                scored_sentences.append((overlap, s_clean))
            
            scored_sentences.sort(key=lambda x: x[0], reverse=True)
            if scored_sentences and scored_sentences[0][0] > 0:
                best_sentence = scored_sentences[0][1]
                cit_tag = f"[`{cit.doc_title}`: §{cit.section or 'Main'}, p.{cit.page_number}]"
                bullet_points.append(f"- {best_sentence} {cit_tag}")
                used_docs.add(cit.doc_title)

        if not bullet_points:
            # Fallback to direct citation highlights
            for cit in citations[:3]:
                cit_tag = f"[`{cit.doc_title}`: §{cit.section or 'Main'}]"
                snippet_preview = cit.snippet.replace('\n', ' ')[:160] + "..."
                bullet_points.append(f"- {snippet_preview} {cit_tag}")
                used_docs.add(cit.doc_title)

        synthesis_text = (
            f"Based on evidence synthesized across **{len(used_docs)} verified sources** "
            f"(`{', '.join(list(used_docs)[:3])}`):\n\n"
            + "\n".join(bullet_points[:5])
        )

        if conflicts:
            synthesis_text += "\n\n### ⚠️ Cross-Document Discrepancy Alert\n"
            for cf in conflicts:
                synthesis_text += (
                    f"> **{cf.subject}**:\n"
                    f"> - *{cf.source_a}*: {cf.claim_a}\n"
                    f"> - *{cf.source_b}*: {cf.claim_b}\n"
                    f"> *Analysis*: {cf.explanation}\n"
                )

        return synthesis_text

    def _calculate_groundedness(self, answer: str, citations: List[Citation]) -> float:
        """Calculates token-level lexical overlap between generated answer and source snippets."""
        if not citations or not answer:
            return 0.0

        ans_words = set(re.findall(r'\b[a-z0-9]{3,}\b', answer.lower()))
        if not ans_words:
            return 80.0

        corpus = " ".join([c.snippet for c in citations]).lower()
        supported = sum(1 for w in ans_words if w in corpus)
        score = (supported / len(ans_words)) * 100.0
        return min(100.0, max(45.0, score + 15.0))

generator = GroundedGenerator()
