import time
from typing import List, Dict, Any, Tuple
from veritas_rag.models import EvalTestCase, EvalMetricResult, EvalSummary, SearchFilters, Citation
from veritas_rag.storage import storage_service
from veritas_rag.generator import generator


class BenchmarkEvaluator:
    """
    Retrieval and Groundedness Evaluation Benchmark Suite.
    Implements Hit Rate@k, MRR, Precision@3, and Conflict/Abstention fidelity.

    Abstention test cases are excluded from retrieval metrics (Hit Rate / MRR / Precision)
    and reported separately via abstention_accuracy.
    """

    def __init__(self):
        self.default_test_cases: List[EvalTestCase] = [
            EvalTestCase(
                id="eval_01",
                query="What is the baseline solar panel efficiency standard and warranty period in the 2023 guidelines?",
                expected_doc_titles=["Solar Policy Framework 2023"],
                expected_conflict=False,
                expected_abstention=False,
                category="Single-Source Retrieval"
            ),
            EvalTestCase(
                id="eval_02",
                query="Compare solar panel efficiency and subsidies between the 2023 framework and the 2025 Modernization Act.",
                expected_doc_titles=["Solar Policy Framework 2023", "CleanTech Modernization Act 2025"],
                expected_conflict=True,
                expected_abstention=False,
                category="Multi-Source Synthesis & Conflict"
            ),
            EvalTestCase(
                id="eval_03",
                query="What battery storage roundtrip efficiency and degradation rates are reported for grid storage?",
                expected_doc_titles=["Grid Storage Technical Whitepaper"],
                expected_conflict=False,
                expected_abstention=False,
                category="Technical Performance"
            ),
            EvalTestCase(
                id="eval_04",
                query="What is the current market price of gold in India today?",
                expected_doc_titles=[],
                expected_conflict=False,
                expected_abstention=True,
                category="Out-of-Domain Abstention"
            ),
            EvalTestCase(
                id="eval_05",
                query="How much financial subsidy or rebate is offered for residential clean tech installations?",
                expected_doc_titles=["Solar Policy Framework 2023", "CleanTech Modernization Act 2025"],
                expected_conflict=True,
                expected_abstention=False,
                category="Multi-Source Numerical Comparison"
            ),
            EvalTestCase(
                id="nexora_three_sources",
                query="Explain how solar standards, grid battery efficiency, and the auth gateway incident each affect system reliability.",
                expected_doc_titles=["Solar Policy Framework 2023", "Grid Storage Technical Whitepaper", "Q3 Production Incident Post-Mortem"],
                expected_doc_ids=["doc_solar_2023", "doc_grid_storage", "doc_incident_postmortem"],
                category="Three-Document Synthesis"
            ),
            EvalTestCase(
                id="nexora_distant_sections",
                query="In the 2025 modernization act, what changed in efficiency criteria and smart inverter requirements?",
                expected_doc_titles=["CleanTech Modernization Act 2025"],
                expected_doc_ids=["doc_cleantech_2025"],
                category="Distant-Section Retrieval"
            ),
            EvalTestCase(
                id="nexora_conflicting_values",
                query="What were the old and new residential subsidy amounts, and why did the amount change?",
                expected_doc_titles=["Solar Policy Framework 2023", "CleanTech Modernization Act 2025"],
                expected_doc_ids=["doc_solar_2023", "doc_cleantech_2025"],
                expected_conflict=True,
                category="Conflicting Values"
            ),
            EvalTestCase(
                id="nexora_unanswerable",
                query="What was the exact score in Nexora's 2021 national chemistry exam?",
                expected_doc_titles=[],
                expected_doc_ids=[],
                expected_abstention=True,
                category="Unanswerable"
            )
        ]

    def run_benchmark(self, custom_tests: List[EvalTestCase] = None) -> EvalSummary:
        tests = custom_tests or self.default_test_cases
        results: List[EvalMetricResult] = []

        # Retrieval metrics — only on non-abstention tests
        retrieval_tests = [t for t in tests if not t.expected_abstention]
        abstention_tests = [t for t in tests if t.expected_abstention]

        total_rr = 0.0
        total_hits = 0
        total_prec = 0.0
        correct_conflicts = 0
        correct_abstentions = 0
        total_latency = 0.0
        total_groundedness = 0.0

        # Ablation accumulators — retrieval tests only
        dense_hits = 0
        dense_rr = 0.0
        lexical_hits = 0
        lexical_rr = 0.0

        for t in tests:
            is_abstention_test = t.expected_abstention

            # ---- Ablation: Dense Vector Only (retrieval tests only) ----
            if not is_abstention_test:
                dense_cits, _ = storage_service.hybrid_search(t.query, top_k=5, search_mode="dense")
                d_hit, d_first_rank = self._evaluate_hit(dense_cits, t)
                dense_hits += 1 if d_hit else 0
                dense_rr += (1.0 / d_first_rank) if d_first_rank > 0 else 0.0

                # ---- Ablation: Lexical Only ----
                lex_cits, _ = storage_service.hybrid_search(t.query, top_k=5, search_mode="lexical")
                l_hit, l_first_rank = self._evaluate_hit(lex_cits, t)
                lexical_hits += 1 if l_hit else 0
                lexical_rr += (1.0 / l_first_rank) if l_first_rank > 0 else 0.0

            # ---- Primary: Full Hybrid Search with RRF Fusion ----
            start = time.perf_counter()
            citations, explain = storage_service.hybrid_search(
                t.query, top_k=5, use_hybrid=True, search_mode="hybrid"
            )
            response = generator.generate_response(t.query, citations, explain)
            latency = (time.perf_counter() - start) * 1000

            retrieved_titles = [c.doc_title for c in response.citations]

            if is_abstention_test:
                # Abstention case: correct if model correctly abstained
                hit = response.abstained
                reciprocal_rank = 0.0  # not counted in retrieval metrics
                precision_at_3 = 0.0   # not counted in retrieval metrics
            else:
                # Retrieval case: measure hit/rank among non-abstention citations
                non_abstention_cits = [
                    c for c in response.citations
                    if not c.metadata.get("closest_evidence_insufficient", False)
                ]
                hit, first_rank = self._find_hit(non_abstention_cits, t.expected_doc_titles)
                reciprocal_rank = (1.0 / first_rank) if first_rank > 0 else 0.0

                # precision@3: how many of the top-3 retrieved are relevant / 3
                top3_relevant = sum(
                    1 for c in non_abstention_cits[:3]
                    if any(exp.lower() in c.doc_title.lower() for exp in t.expected_doc_titles)
                )
                precision_at_3 = top3_relevant / 3.0

                total_hits += 1 if hit else 0
                total_rr += reciprocal_rank
                total_prec += precision_at_3

            # Conflict detection accuracy (all tests)
            has_conflict = len(response.conflicts) > 0
            if has_conflict == t.expected_conflict:
                correct_conflicts += 1

            # Abstention accuracy (all tests)
            if response.abstained == t.expected_abstention:
                correct_abstentions += 1

            total_latency += latency
            total_groundedness += response.groundedness_score

            results.append(EvalMetricResult(
                test_id=t.id,
                query=t.query,
                hit=hit,
                reciprocal_rank=round(reciprocal_rank, 3),
                precision_at_k=round(precision_at_3, 3),
                retrieved_titles=retrieved_titles[:3],
                expected_titles=t.expected_doc_titles,
                retrieved_doc_ids=list(dict.fromkeys(c.doc_id for c in response.citations)),
                expected_doc_ids=t.expected_doc_ids,
                conflict_detected=has_conflict,
                expected_conflict=t.expected_conflict,
                abstained=response.abstained,
                expected_abstention=t.expected_abstention,
                latency_ms=round(latency, 1),
                groundedness_score=response.groundedness_score
            ))

        n = len(tests)
        n_ret = max(1, len(retrieval_tests))  # avoid division by zero

        return EvalSummary(
            total_tests=n,
            hit_rate=round(total_hits / n_ret, 3),
            mrr=round(total_rr / n_ret, 3),
            precision_at_3=round(total_prec / n_ret, 3),
            conflict_detection_accuracy=round(correct_conflicts / max(1, n), 3),
            abstention_accuracy=round(correct_abstentions / max(1, n), 3),
            avg_latency_ms=round(total_latency / n, 1) if n > 0 else 0.0,
            avg_groundedness=round(total_groundedness / n, 1) if n > 0 else 0.0,
            # Ablation metrics (computed over retrieval tests only)
            dense_hit_rate=round(dense_hits / n_ret, 3),
            dense_mrr=round(dense_rr / n_ret, 3),
            lexical_hit_rate=round(lexical_hits / n_ret, 3),
            lexical_mrr=round(lexical_rr / n_ret, 3),
            hybrid_hit_rate=round(total_hits / n_ret, 3),
            hybrid_mrr=round(total_rr / n_ret, 3),
            results=results
        )

    def _evaluate_hit(self, citations: List[Citation], test: EvalTestCase) -> Tuple[bool, int]:
        """Returns (hit, first_rank) for ablation scoring."""
        if test.expected_abstention:
            return True, 1  # abstention tests always count as hit in ablation
        return self._find_hit(citations, test.expected_doc_titles)

    def _find_hit(self, citations: List[Citation], expected_titles: List[str]) -> Tuple[bool, int]:
        """Returns (hit, 1-based rank of first relevant result) for a citation list."""
        for idx, c in enumerate(citations):
            if any(
                exp.lower() in c.doc_title.lower() or exp.lower() == c.doc_id.lower()
                for exp in expected_titles
            ):
                return True, idx + 1
        return False, 0


benchmark_evaluator = BenchmarkEvaluator()
