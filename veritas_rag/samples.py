from typing import List, Dict, Any
from veritas_rag.models import DocumentUploadRequest
from veritas_rag.chunker import chunker
from veritas_rag.storage import storage_service
import uuid
import hashlib

SAMPLE_DATASETS: List[Dict[str, Any]] = [
    {
        "id": "doc_solar_2023",
        "title": "Solar Policy Framework 2023",
        "author": "Department of Energy & Climate (2023)",
        "year": 2023,
        "category": "Clean Energy",
        "content": """# Solar Policy Framework 2023: Guidelines and Technical Standards

## Executive Summary
This document establishes regulatory baselines for commercial and residential photovoltaic deployment across federal and state grids.

## Technical Specifications & Efficiency
Under Section 4.1, all approved monocrystalline photovoltaic modules must achieve a minimum tested solar panel efficiency of 18.0%. Modules operating under ambient operating temperatures must maintain degradation under 0.8% annually.

## Warranty and Guarantee Standards
Installers must offer a minimum mandatory manufacturer warranty of 3 years covering inverters, racking systems, and panel output performance. Any defect reported within this period must be remediated at zero consumer cost.

## Financial Subsidies & Rebates
Under the Residential Clean Energy Initiative (RCEI), qualifying households are eligible for a direct government subsidy rebate of $5,000 for installations exceeding 4.5 kW capacity. Application processing requires manual submission of municipal permits.

## Grid Interconnection Requirements
Interconnection approval is mandatory prior to grid tie-in. Systems exceeding 10 kW must deploy external bidirectional disconnection meters inspected by utility engineers."""
    },
    {
        "id": "doc_cleantech_2025",
        "title": "CleanTech Modernization Act 2025",
        "author": "Federal Energy Regulatory Commission (2025)",
        "year": 2025,
        "category": "Clean Energy",
        "content": """# CleanTech Modernization Act 2025: Updated Mandates & Standards

## Legislative Overview
This Act updates and supersedes previous 2023 baseline provisions to accelerate high-efficiency solar and storage integration.

## Modernized Efficiency Criteria
To promote next-generation perovskite-silicon tandem cells, Section 3.2 raises the minimum required solar panel efficiency standard to 22.0%. Panels falling below this revised threshold are prohibited from receiving federal certifications.

## Extended Warranty Obligations
Recognizing advancements in manufacturing reliability, the mandatory equipment warranty period is extended to 5 years (superseding the former 3-year term). Warranty obligations now encompass battery management micro-controllers.

## Revised Subsidy Cap & Automatic Approval
Due to budgetary realignment and declining panel production costs, the direct residential subsidy rebate is now capped at $3,500 per installation (revised downward from $5,000). However, approval is now automatically granted through the digital portal upon certificate upload.

## Smart Inverter Standards
All installations must incorporate IEEE 1547-2018 compliant smart inverters capable of autonomous voltage regulation and anti-islanding protection."""
    },
    {
        "id": "doc_grid_storage",
        "title": "Grid Storage Technical Whitepaper",
        "author": "National Renewable Energy Lab (2024)",
        "year": 2024,
        "category": "Clean Energy",
        "content": """# Grid-Scale Battery Energy Storage Systems: Performance and Degradation

## Storage Overview
Large-scale lithium iron phosphate (LFP) and sodium-ion battery chemistries serve as essential grid stabilizing assets for variable solar irradiance.

## Roundtrip Efficiency & Metrics
Industrial utility-scale battery storage facilities report an average AC-to-AC roundtrip efficiency of 86.5% under standard cycling profiles (1 C charge / 1 C discharge). Parasitic HVAC cooling loads reduce net roundtrip efficiency to approximately 82.0% in high ambient thermal environments.

## Degradation Rates & Lifecycle
State-of-the-art LFP cells exhibit capacity degradation rates of less than 1.8% per 1,000 equivalent full cycles. Cell end-of-life is defined when retained capacity drops below 70% of nominal rating, typically attained after 6,500 to 8,000 cycles.

## Capital Expenditure Trends
System-level battery storage costs have declined to $195 per kWh for 4-hour duration installations, with battery cells representing 48% of total balance of system costs."""
    },
    {
        "id": "doc_arch_spec",
        "title": "Auth Service Architecture Spec v3",
        "author": "Core Platform Engineering (2025)",
        "year": 2025,
        "category": "Software Infrastructure",
        "content": """# Auth Service Architecture Spec v3

## System Architecture
The Authentication Service acts as the centralized identity provider for the distributed microservices ecosystem. It issues cryptographically signed JWT tokens backed by Ed25519 asymmetric keypairs.

## SLA & Latency Requirements
Target P99 authentication latency is bounded at 25 ms. Token verification is performed statelessly across API edge gateways using cached public keys refreshed every 6 hours.

## High Availability & Failover
The service is deployed in active-active topology across three availability zones. Distributed Redis clusters handle session revocation blacklists with a replication timeout limit of 15 ms."""
    },
    {
        "id": "doc_incident_postmortem",
        "title": "Q3 Production Incident Post-Mortem",
        "author": "Site Reliability Engineering (2025)",
        "year": 2025,
        "category": "Software Infrastructure",
        "content": """# Incident Post-Mortem: Auth Gateway Cascade Failure (INC-4092)

## Incident Summary
On August 14, 2025, the primary token verification gateway experienced a cascading latency spike, leading to a 14-minute disruption of user sign-in workflows.

## Root Cause Analysis
During a network partition between AZ-1 and AZ-2, the session revocation blacklist sync exceeded the standard 15 ms replication timeout, peaking at 480 ms. This saturated edge connection pools.

## Remediation Actions
1. Upgraded edge proxy circuit breaker trip thresholds.
2. Implemented local fallback memory caching for revocation lists during temporary network partitions.
3. Updated monitoring alerts for replication latency exceeding 50 ms."""
    }
]

def load_sample_datasets(force_reload: bool = False):
    """Initializes knowledge base with rich multi-document datasets idempotently."""
    loaded_count = 0
    for item in SAMPLE_DATASETS:
        if not force_reload and item["id"] in storage_service._documents:
            continue
        meta = {
            "title": item["title"],
            "author": item["author"],
            "year": item["year"],
            "category": item["category"],
            "source_type": "preloaded",
            "file_size_bytes": len(item["content"].encode("utf-8")),
            "content_hash": hashlib.sha256(item["content"].encode("utf-8")).hexdigest()[:16]
        }
        storage_service.add_document(item["id"], item["title"], meta, item["content"])
        chunks = chunker.chunk_document(item["id"], item["title"], item["content"], meta)
        storage_service.add_chunks(chunks)
        loaded_count += 1
    if loaded_count > 0:
        print(f"[Samples] Successfully loaded {loaded_count} benchmark documents.")
