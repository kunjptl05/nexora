import time
from typing import List, Dict, Any
from veritas_rag.models import EvalTestCase, EvalMetricResult, EvalSummary, SearchFilters
from veritas_rag.storage import storage_service
from veritas_rag.generator import generator

class BenchmarkEvaluator:
    """
    Retrieval and Groundedness Evaluation Benchmark Suite.
    Implements Hit Rate@k, MRR, Precision@k, and Conflict/Abstention fidelity.
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
            )
        ]

    def run_benchmark(self, custom_tests: List[EvalTestCase] = None) -> EvalSummary:
        tests = custom_tests or self.default_test_cases
        results: List[EvalMetricResult] = []

        total_rr = 0.0
        total_hits = 0
        total_prec = 0.0
        correct_conflicts = 0
        correct_abstentions = 0
        total_latency = 0.0
        total_groundedness = 0.0

        for t in tests:
            start = time.perf_counter()
            citations, explain = storage_service.hybrid_search(t.query, top_k=5, use_hybrid=True)
            response = generator.generate_response(t.query, citations, explain)
            latency = (time.perf_counter() - start) * 1000

            retrieved_titles = [c.doc_title for c in response.citations]
            
            # Check Hit and Reciprocal Rank
            hit = False
            first_rank = 0
            relevant_count = 0

            if t.expected_abstention:
                hit = response.abstained
                reciprocal_rank = 1.0 if response.abstained else 0.0
                precision_at_3 = 1.0 if response.abstained else 0.0
            else:
                for idx, title in enumerate(retrieved_titles):
                    if any(exp.lower() in title.lower() for exp in t.expected_doc_titles):
                        if not hit:
                            hit = True
                            first_rank = idx + 1
                        relevant_count += 1
                reciprocal_rank = 1.0 / first_rank if first_rank > 0 else 0.0
                precision_at_3 = min(1.0, relevant_count / min(3, max(1, len(t.expected_doc_titles))))

            # Check Conflict Detection
            has_conflict = len(response.conflicts) > 0
            if has_conflict == t.expected_conflict:
                correct_conflicts += 1

            # Check Abstention
            if response.abstained == t.expected_abstention:
                correct_abstentions += 1

            total_hits += (1 if hit else 0)
            total_rr += reciprocal_rank
            total_prec += precision_at_3
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
                conflict_detected=has_conflict,
                expected_conflict=t.expected_conflict,
                abstained=response.abstained,
                expected_abstention=t.expected_abstention,
                latency_ms=round(latency, 1),
                groundedness_score=response.groundedness_score
            ))

        n = len(tests)
        return EvalSummary(
            total_tests=n,
            hit_rate=round(total_hits / n, 3) if n > 0 else 0.0,
            mrr=round(total_rr / n, 3) if n > 0 else 0.0,
            precision_at_3=round(total_prec / n, 3) if n > 0 else 0.0,
            conflict_detection_accuracy=round(correct_conflicts / n, 3) if n > 0 else 0.0,
            abstention_accuracy=round(correct_abstentions / n, 3) if n > 0 else 0.0,
            avg_latency_ms=round(total_latency / n, 1) if n > 0 else 0.0,
            avg_groundedness=round(total_groundedness / n, 1) if n > 0 else 0.0,
            results=results
        )

benchmark_evaluator = BenchmarkEvaluator()
