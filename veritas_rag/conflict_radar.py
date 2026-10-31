import re
from typing import List, Dict, Any, Tuple, Optional
from veritas_rag.models import Citation, ConflictItem
import uuid

class ConflictRadar:
    """
    Automated Cross-Document Claim Reconciliation Engine.
    Performs semantic claim extraction, delta calculations, and version comparison.
    """

    def _extract_domain(self, text: str, doc_title: str) -> str:
        combined = (text + " " + doc_title).lower()
        # Use token/phrase boundaries: e.g. "pv" must not match "pvc",
        # "auth" must not match "author", and "cycle" must not match "bicycle".
        if re.search(r"\b(solar|photovoltaic|pv|panel|perovskite|monocrystalline)\b", combined):
            return "solar_pv"
        if re.search(r"\b(battery|batteries|bess|lfp|roundtrip|cycle|cycles|cooling)\b|\bgrid\s+storage\b", combined):
            return "battery_storage"
        if re.search(r"\b(auth|authentication|jwt|gateway|token|session|redis|latency)\b", combined):
            return "software_auth"
        return "general"

    def _normalize_unit(self, currency: str, unit: str) -> str:
        raw = (currency or unit or "").strip().lower()
        aliases = {
            "%": "percent", "percent": "percent", "percentage": "percent",
            "year": "years", "years": "years", "yr": "years", "yrs": "years",
            "month": "months", "months": "months", "day": "days", "days": "days",
            "second": "seconds", "seconds": "seconds", "sec": "seconds", "s": "seconds",
            "usd": "usd", "$": "usd", "inr": "inr", "₹": "inr", "eur": "eur", "€": "eur",
            "ms": "ms", "kw": "kw", "kwh": "kwh", "gb": "gb", "mb": "mb"
        }
        return aliases.get(raw, raw)

    def _sentence_for_term(self, text: str, term: str) -> str:
        sentences = re.split(r'(?<=[.!?;])\s+|\n+', text)
        return next(
            (sentence for sentence in sentences
             if re.search(rf'\b{re.escape(term)}\b', sentence, re.IGNORECASE)),
            text
        )

    def detect_conflicts(self, citations: List[Citation], query: str) -> List[ConflictItem]:
        if len(citations) < 2:
            return []

        # Check if the query is an isolated single-version query (e.g. only mentions '2023 guidelines')
        years_in_query = re.findall(r'\b(202[0-9])\b', query)
        is_comparative = any(w in query.lower() for w in [
            "compare", "vs", "versus", "between", "difference", "discrepancy", 
            "contradict", "change", "changed", "updated", "revision", "difference between", "compared to"
        ]) or len(years_in_query) >= 2

        # If user explicitly asked only about a single year/standard without comparison words, don't invent conflict
        if len(years_in_query) == 1 and not is_comparative:
            target_year = int(years_in_query[0])
            citations = [c for c in citations if c.metadata.get("year") == target_year or str(target_year) in c.doc_title]
            if len(citations) < 2:
                return []

        conflicts: List[ConflictItem] = []
        
        # 1. Structured numerical claim extraction with Delta calculation
        num_conflicts = self._check_numerical_discrepancies(citations)
        conflicts.extend(num_conflicts)

        # 2. Check for policy & temporal revisions (e.g., 2023 vs 2025 updates)
        if is_comparative:
            temporal_conflicts = self._check_policy_revisions(citations)
            conflicts.extend(temporal_conflicts)

        # 3. Check for polarity opposites (mandatory vs optional, allowed vs prohibited)
        polarity_conflicts = self._check_polarity_conflicts(citations)
        conflicts.extend(polarity_conflicts)

        return conflicts

    def _check_numerical_discrepancies(self, citations: List[Citation]) -> List[ConflictItem]:
        """Extracts structured metric claims and calculates mathematical deltas."""
        findings = []
        metrics_pattern = re.compile(
            r'(\b(?:efficiency|warranty|guarantee|cost|price|rebate|subsidy|fee|sla|uptime|latency|timeout|limit)\b[^\.\n;]{1,60}?(?:(\$|₹|€)?\s*(\d+(?:\.\d+)?)\s*(%|years?|months?|days?|ms|seconds?|usd|inr|gb|mb|kw|kwh)?))',
            re.IGNORECASE
        )

        extracted: List[Dict[str, Any]] = []
        for cit in citations:
            matches = metrics_pattern.findall(cit.snippet)
            for full_match, currency, num_str, unit in matches:
                metric_match = re.findall(r'\b(?:efficiency|warranty|guarantee|cost|price|rebate|subsidy|fee|sla|uptime|latency|timeout|limit)\b', full_match, re.IGNORECASE)
                if metric_match:
                    m = metric_match[0].lower()
                    try:
                        numeric_val = float(num_str)
                    except ValueError:
                        numeric_val = None

                    unit_clean = (currency or unit or "").strip()
                    display_val = f"{currency or ''}{num_str} {unit or ''}".strip()
                    domain = self._extract_domain(cit.snippet, cit.doc_title)

                    extracted.append({
                        "metric": m,
                        "domain": domain,
                        "raw_statement": full_match.strip(),
                        "display_val": display_val,
                        "numeric_val": numeric_val,
                        "unit": unit_clean,
                        "normalized_unit": self._normalize_unit(currency, unit),
                        "doc_title": cit.doc_title,
                        "doc_id": cit.doc_id,
                        "section": cit.section or "Section",
                        "page": cit.page_number,
                        "year": cit.metadata.get("year")
                    })

        # Compare pairs across different documents within the same semantic domain
        for i in range(len(extracted)):
            for j in range(i + 1, len(extracted)):
                e1 = extracted[i]
                e2 = extracted[j]
                units_match = e1["normalized_unit"] == e2["normalized_unit"]
                if (e1["doc_id"] != e2["doc_id"]
                        and e1["metric"] == e2["metric"]
                        and e1["domain"] == e2["domain"]
                        and units_match):
                    if e1["display_val"] != e2["display_val"]:
                        # Calculate quantitative delta if both numeric
                        delta_str = None
                        if e1["numeric_val"] is not None and e2["numeric_val"] is not None:
                            # Order by year/revision if available
                            if (e1["year"] is not None and e2["year"] is not None
                                    and e2["year"] < e1["year"]):
                                diff = e1["numeric_val"] - e2["numeric_val"]
                                older, newer = e2, e1
                            else:
                                diff = e2["numeric_val"] - e1["numeric_val"]
                                older, newer = e1, e2
                            
                            sign = "+" if diff > 0 else ""
                            if "%" in (older["unit"] + newer["unit"]):
                                delta_str = f"{sign}{diff:.1f}%"
                            elif older["normalized_unit"] in {"usd", "inr", "eur"}:
                                delta_str = f"{sign}{diff:,.0f} {older['normalized_unit'].upper()}"
                            elif "year" in (older["unit"] + newer["unit"]):
                                delta_str = f"{sign}{int(diff) if diff.is_integer() else diff:.1f} years"
                            elif "ms" in (older["unit"] + newer["unit"]):
                                delta_str = f"{sign}{diff:.0f} ms"
                            else:
                                delta_str = f"{sign}{diff:.1f}"

                        c = ConflictItem(
                            id=f"cnf_{uuid.uuid4().hex[:6]}",
                            subject=f"Discrepancy: {e1['metric'].capitalize()} Standard",
                            claim_a=f"{e1['raw_statement']}",
                            source_a=f"{e1['doc_title']} (p.{e1['page']})",
                            value_a=e1["display_val"],
                            claim_b=f"{e2['raw_statement']}",
                            source_b=f"{e2['doc_title']} (p.{e2['page']})",
                            value_b=e2["display_val"],
                            delta=delta_str,
                            unit=e1["unit"] or e2["unit"],
                            condition=f"{e1['doc_title']} vs {e2['doc_title']}",
                            discrepancy_type="quantitative",
                            severity="high",
                            explanation=f"Contrasting values for {e1['metric']}: '{e1['display_val']}' in {e1['doc_title']} vs '{e2['display_val']}' in {e2['doc_title']}." + (f" Net difference: {delta_str}." if delta_str else "")
                        )
                        # Avoid duplicates
                        if not any(x.subject == c.subject and x.source_a == c.source_a and x.source_b == c.source_b for x in findings):
                            findings.append(c)

        return findings

    def _check_policy_revisions(self, citations: List[Citation]) -> List[ConflictItem]:
        findings = []
        keywords = ["supersedes", "superseded", "replaces", "replaced", "revokes", "revoked", "repeals", "repealed", "amends", "amended"]
        
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
                has_policy_change = any(re.search(rf"\b{k}\b", older_cit.snippet + " " + newer_cit.snippet, re.IGNORECASE) for k in keywords)
                if has_policy_change:
                    findings.append(ConflictItem(
                        id=f"cnf_{uuid.uuid4().hex[:6]}",
                        subject=f"Policy Evolution ({older_year} -> {newer_year})",
                        claim_a=f"{older_cit.doc_title} ({older_year}) baseline standard",
                        source_a=f"{older_cit.doc_title} ({older_year})",
                        value_a=f"v{older_year}",
                        claim_b=f"{newer_cit.doc_title} ({newer_year}) updated amendments",
                        source_b=f"{newer_cit.doc_title} ({newer_year})",
                        value_b=f"v{newer_year}",
                        delta=f"Amended in {newer_year}",
                        condition="Version Revision",
                        discrepancy_type="policy_revision",
                        severity="medium",
                        explanation=f"The {newer_year} publication modifies and supersedes procedural clauses from the {older_year} framework."
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
        generic_terms = {
            "this", "that", "with", "from", "shall", "must", "will", "not",
            "when", "then", "than", "they", "their", "these", "those",
            "policy", "standard", "rule", "requirement", "document", "section"
        }

        for word_a, word_b in polar_pairs:
            matches_a = [
                (citation, self._sentence_for_term(citation.snippet, word_a))
                for citation in citations
                if re.search(rf'\b{word_a}\b', citation.snippet, re.IGNORECASE)
            ]
            matches_b = [
                (citation, self._sentence_for_term(citation.snippet, word_b))
                for citation in citations
                if re.search(rf'\b{word_b}\b', citation.snippet, re.IGNORECASE)
            ]

            for ca, sentence_a in matches_a:
                for cb, sentence_b in matches_b:
                    if ca.doc_id == cb.doc_id:
                        continue
                    anchors_a = set(re.findall(r'\b[a-z]{4,}\b', sentence_a.lower())) - generic_terms - {word_a, word_b}
                    anchors_b = set(re.findall(r'\b[a-z]{4,}\b', sentence_b.lower())) - generic_terms - {word_a, word_b}
                    if not anchors_a.intersection(anchors_b):
                        continue

                    findings.append(ConflictItem(
                        id=f"cnf_{uuid.uuid4().hex[:6]}",
                        subject=f"Possible rule difference: '{word_a}' vs '{word_b}'",
                        claim_a=f"{sentence_a.strip()}",
                        source_a=f"{ca.doc_title} [{ca.section}]",
                        value_a=word_a.upper(),
                        claim_b=f"{sentence_b.strip()}",
                        source_b=f"{cb.doc_title} [{cb.section}]",
                        value_b=word_b.upper(),
                        delta="Review required",
                        condition="Shared subject terms found in both passages",
                        discrepancy_type="contradictory",
                        severity="medium",
                        explanation=(
                            f"The passages use opposite terms ({word_a.upper()} and {word_b.upper()}) "
                            "and share subject wording. Verify that their scope, date, and conditions match."
                        )
                    ))

        return findings

conflict_radar = ConflictRadar()
