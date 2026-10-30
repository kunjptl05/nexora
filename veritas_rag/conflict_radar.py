import re
from typing import List, Dict, Any, Tuple
from veritas_rag.models import Citation, ConflictItem
import uuid

class ConflictRadar:
    """
    Automated Cross-Document Claim Reconciliation Engine.
    Scans retrieved passages for numerical, policy, or polarity contradictions.
    """

    def detect_conflicts(self, citations: List[Citation], query: str) -> List[ConflictItem]:
        if len(citations) < 2:
            return []

        conflicts: List[ConflictItem] = []
        
        # 1. Check for numerical discrepancy on common metrics
        num_conflicts = self._check_numerical_discrepancies(citations)
        conflicts.extend(num_conflicts)

        # 2. Check for policy & temporal revisions (e.g., 2023 vs 2025 updates)
        temporal_conflicts = self._check_policy_revisions(citations)
        conflicts.extend(temporal_conflicts)

        # 3. Check for polarity opposites (mandatory vs optional, allowed vs prohibited)
        polarity_conflicts = self._check_polarity_conflicts(citations)
        conflicts.extend(polarity_conflicts)

        return conflicts

    def _check_numerical_discrepancies(self, citations: List[Citation]) -> List[ConflictItem]:
        """Detects conflicting numbers associated with identical nouns/keywords."""
        findings = []
        metrics_pattern = re.compile(
            r'(\b(?:efficiency|warranty|guarantee|cost|price|rebate|subsidy|fee|sla|uptime|latency|throughput|timeout|limit)\b[^\.\n;]{1,60}?(\d+(?:\.\d+)?(?:\s*(?:%|years?|months?|days?|ms|seconds?|usd|\$|inr|₹|gb|mb|kw|kwh))?))',
            re.IGNORECASE
        )

        extracted: List[Dict[str, Any]] = []
        for cit in citations:
            matches = metrics_pattern.findall(cit.snippet)
            for full_match, val in matches:
                # normalize metric name
                metric_name = re.findall(r'\b(?:efficiency|warranty|guarantee|cost|price|rebate|subsidy|fee|sla|uptime|latency|throughput|timeout|limit)\b', full_match, re.IGNORECASE)
                if metric_name:
                    m = metric_name[0].lower()
                    extracted.append({
                        "metric": m,
                        "raw_statement": full_match.strip(),
                        "value": val.strip(),
                        "doc_title": cit.doc_title,
                        "doc_id": cit.doc_id,
                        "section": cit.section or "Section",
                        "page": cit.page_number
                    })

        # Compare pairs across different documents
        for i in range(len(extracted)):
            for j in range(i + 1, len(extracted)):
                e1 = extracted[i]
                e2 = extracted[j]
                if e1["doc_id"] != e2["doc_id"] and e1["metric"] == e2["metric"]:
                    if e1["value"] != e2["value"]:
                        # Found discrepancy!
                        c = ConflictItem(
                            id=f"cnf_{uuid.uuid4().hex[:6]}",
                            subject=f"Conflicting {e1['metric'].capitalize()} Values",
                            claim_a=f"'{e1['raw_statement']}' ({e1['doc_title']}, {e1['section']})",
                            source_a=f"{e1['doc_title']} [p.{e1['page']}]",
                            claim_b=f"'{e2['raw_statement']}' ({e2['doc_title']}, {e2['section']})",
                            source_b=f"{e2['doc_title']} [p.{e2['page']}]",
                            discrepancy_type="quantitative",
                            severity="high",
                            explanation=f"Different documents cite contrasting figures for {e1['metric']}: {e1['value']} vs {e2['value']}. This typically indicates differing revisions, testing conditions, or policy tiers."
                        )
                        # Avoid duplicates
                        if not any(x.subject == c.subject and x.source_a == c.source_a and x.source_b == c.source_b for x in findings):
                            findings.append(c)

        return findings

    def _check_policy_revisions(self, citations: List[Citation]) -> List[ConflictItem]:
        findings = []
        keywords = ["eligible", "approved", "supersedes", "revoked", "replaced", "updated", "deprecated"]
        
        # Check if citations mention version differences (e.g. 2023 vs 2025)
        doc_years = {}
        for c in citations:
            year = c.metadata.get("year")
            if not year:
                match = re.search(r'\b(202[0-9])\b', c.doc_title + " " + c.snippet)
                if match:
                    year = int(match.group(1))
            if year:
                doc_years[c.doc_id] = (year, c)

        if len(doc_years) >= 2:
            sorted_docs = sorted(doc_years.values(), key=lambda x: x[0])
            older_year, older_cit = sorted_docs[0]
            newer_year, newer_cit = sorted_docs[-1]
            if newer_year > older_year:
                # Check for policy terms
                has_policy_change = any(k in older_cit.snippet.lower() or k in newer_cit.snippet.lower() for k in keywords)
                if has_policy_change:
                    findings.append(ConflictItem(
                        id=f"cnf_{uuid.uuid4().hex[:6]}",
                        subject=f"Temporal Policy Evolution ({older_year} vs {newer_year})",
                        claim_a=f"{older_cit.doc_title} ({older_year}) baseline regulations",
                        source_a=f"{older_cit.doc_title} ({older_year})",
                        claim_b=f"{newer_cit.doc_title} ({newer_year}) updated terms",
                        source_b=f"{newer_cit.doc_title} ({newer_year})",
                        discrepancy_type="policy_revision",
                        severity="medium",
                        explanation=f"The newer {newer_year} document reflects amended rules or technical criteria that modify clauses in the {older_year} publication."
                    ))

        return findings

    def _check_polarity_conflicts(self, citations: List[Citation]) -> List[ConflictItem]:
        findings = []
        polar_pairs = [
            ("mandatory", "optional"),
            ("required", "recommended"),
            ("allowed", "prohibited"),
            ("permitted", "forbidden"),
            ("deprecated", "supported")
        ]

        for word_a, word_b in polar_pairs:
            matches_a = [c for c in citations if re.search(rf'\b{word_a}\b', c.snippet, re.IGNORECASE)]
            matches_b = [c for c in citations if re.search(rf'\b{word_b}\b', c.snippet, re.IGNORECASE)]

            for ca in matches_a:
                for cb in matches_b:
                    if ca.doc_id != cb.doc_id:
                        findings.append(ConflictItem(
                            id=f"cnf_{uuid.uuid4().hex[:6]}",
                            subject=f"Direct Rule Contradiction: '{word_a}' vs '{word_b}'",
                            claim_a=f"Asserts condition is '{word_a}' in {ca.doc_title}",
                            source_a=f"{ca.doc_title} [{ca.section}]",
                            claim_b=f"Asserts condition is '{word_b}' in {cb.doc_title}",
                            source_b=f"{cb.doc_title} [{cb.section}]",
                            discrepancy_type="contradictory",
                            severity="high",
                            explanation=f"One document treats the requirement as {word_a.upper()} while another treats it as {word_b.upper()}."
                        ))

        return findings

conflict_radar = ConflictRadar()
