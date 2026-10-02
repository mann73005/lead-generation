"""Lead discovery agent.

A bounded search-then-extract flow, which is what the brief asks for — not a
self-replanning agent. The model may issue several rounds of tool calls, but
the loop has a hard turn limit and the extraction step is a separate,
tool-free call with a response schema. That keeps the run cheap, finite, and
explainable in a transcript.

    ICP -> search(query)* -> fetch(urls)* -> structured extraction
        -> Pydantic validation -> business validation -> PostgreSQL

Every URL the agent opens is recorded. Extraction is then held to that set:
a lead citing a page the agent never read is discarded, not stored with a
caveat.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.schemas import EXTRACTION_JSON_SCHEMA, ExtractedLead, ExtractionResult
from app.ai.validation import validate_candidates
from app.core.exceptions import ProviderError
from app.core.logging import get_logger
from app.core.policy import DiscoveryPolicy, load_discovery_policy, load_product_config
from app.models import ICP, Company, DiscoveryRun, Lead
from app.models.enums import DiscoveryRunStatus
from app.providers import (
    Message,
    ToolResult,
    ToolSpec,
    get_fetch_provider,
    get_llm_provider,
    get_search_provider,
)
from app.services.lead_scores import apply_score

logger = get_logger(__name__)

# Budgets, source rules, seed queries and prompts all come from
# `config/discovery.yaml`. The only things defined here are the tool
# signatures, which are part of the code's contract with the model rather than
# a tuning knob.

SEARCH_TOOL = ToolSpec(
    name="search",
    description=(
        "Search the web and return ranked results with titles, URLs and snippets. "
        "Use targeted queries naming the industry, region and job title."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query."},
            "max_results": {"type": "integer", "description": "1-10, default 5."},
        },
        "required": ["query"],
    },
)

FETCH_TOOL = ToolSpec(
    name="fetch_page",
    description=(
        "Open one or more URLs from search results and return their readable text. "
        "You must fetch a page before citing it."
    ),
    parameters={
        "type": "object",
        "properties": {
            "urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Up to 5 URLs taken verbatim from search results.",
            }
        },
        "required": ["urls"],
    },
)



@lru_cache(maxsize=4)
def _gated_site_pattern(domains: tuple[str, ...]) -> re.Pattern[str]:
    """Matches a `site:` operator pointing at a domain we will discard anyway."""
    alternatives = "|".join(d.replace(".", r"\.") for d in domains)
    return re.compile(rf"\bsite:(?:\S*\.)?(?:{alternatives})\S*", re.IGNORECASE)


def _is_readable(url: str, policy: DiscoveryPolicy) -> bool:
    """Whether a URL is worth fetching and legitimate to cite.

    Excludes login-gated sites, whose extraction returns the wall rather than
    the page, and job boards, which list vacancies rather than the people who
    hold them. Both would otherwise dominate a title search.
    """
    parsed = urlparse(url.lower())
    host = parsed.netloc.removeprefix("www.")
    if not host:
        return False
    if any(host == d or host.endswith(f".{d}") for d in policy.sources.gated_domains):
        return False
    return not any(marker in parsed.path for marker in policy.sources.job_path_markers)


def _strip_gated_operators(query: str, policy: DiscoveryPolicy) -> str:
    """Remove `site:` operators aimed at sources we refuse.

    Left in, they guarantee a page of results that is then thrown away — the
    model spends a search and learns nothing.
    """
    cleaned = _gated_site_pattern(tuple(policy.sources.gated_domains)).sub("", query)
    # Tidy up the "OR OR" and dangling operators the removal leaves behind.
    cleaned = re.sub(r"\b(OR|AND)\b(\s+\b(OR|AND)\b)+", r"\1", cleaned)
    cleaned = re.sub(r"^\s*(OR|AND)\b|\b(OR|AND)\s*$", "", cleaned).strip()
    return re.sub(r"\s{2,}", " ", cleaned) or query


def _seed_queries(icp: ICP, policy: DiscoveryPolicy) -> list[str]:
    """Opening searches derived from the ICP, no model involved.

    Templates come from `config/discovery.yaml`; only the substitution happens
    here.
    """
    spec = policy.seed_queries
    scope = f"{icp.industry} {icp.region}".strip()
    values = {"scope": scope, "keywords": " ".join(icp.keywords[:3])}

    queries = [
        spec.per_title.format(title=title, **values) for title in icp.titles[: spec.max_titles]
    ]
    queries.extend(template.format(**values) for template in spec.global_)
    if icp.keywords and spec.with_keywords:
        queries.append(spec.with_keywords.format(**values))

    # De-duplicated: two ICP titles can render the same query.
    seen: list[str] = []
    for query in queries:
        if query not in seen:
            seen.append(query)
    return seen[: spec.max_queries]


def _tool_result(call_id: str, name: str, content: Any) -> ToolResult:
    return ToolResult(call_id=call_id, name=name, content=content)


def run_discovery(db: Session, icp: ICP, *, requested_count: int = 8) -> DiscoveryRun:
    """Execute one discovery run and persist whatever survives validation."""
    run = DiscoveryRun(
        icp_id=icp.id,
        requested_count=requested_count,
        status=DiscoveryRunStatus.RUNNING,
        started_at=datetime.now(UTC),
    )
    db.add(run)
    db.flush()

    transcript: list[dict[str, Any]] = []
    visited_urls: set[str] = set()
    searches = 0
    fetches = 0

    try:
        policy = load_discovery_policy()
        limits = policy.limits
        product = load_product_config().identity
        system_prompt = policy.prompts.system.format(
            product_name=product.name, product_description=product.description
        )

        llm = get_llm_provider()
        search_provider = get_search_provider()
        fetch_provider = get_fetch_provider()

        brief = (
            f"Find up to {requested_count} leads matching this profile.\n"
            f"Industry: {icp.industry}\n"
            f"Region: {icp.region}\n"
            f"Company size: {icp.employee_min or 'any'}-{icp.employee_max or 'any'} employees\n"
            f"Target job titles: {', '.join(icp.titles)}\n"
            + (f"Keywords: {', '.join(icp.keywords)}\n" if icp.keywords else "")
        )
        messages = [Message(role="user", text=brief)]
        #: Every readable URL search has surfaced, in rank order.
        candidate_urls: list[str] = []

        # ---- Phase A0: deterministic seed ----------------------------------
        # The first searches are built from the ICP rather than asked for. Two
        # reasons: it removes several LLM round trips from a rate-limited free
        # tier, and it guarantees the model starts with real evidence instead
        # of spending its whole turn budget refining queries. This is the
        # "search" half of search-then-extract; the loop below is optional
        # refinement on top of it.
        for query in _seed_queries(icp, policy):
            searches += 1
            hits = [h for h in search_provider.search(query, max_results=5) if _is_readable(h.url, policy)]
            candidate_urls.extend(h.url for h in hits if h.url not in candidate_urls)
            transcript.append(
                {"stage": "seed", "tool": "search", "query": query, "results": len(hits)}
            )

        seed_pages = fetch_provider.fetch(candidate_urls[:limits.seed_fetch_count], max_chars=limits.page_char_budget)
        fetches += len(seed_pages)
        visited_urls.update(p.url for p in seed_pages)
        transcript.append(
            {"stage": "seed", "tool": "fetch_page", "retrieved": [p.url for p in seed_pages]}
        )

        if seed_pages:
            messages.append(
                Message(
                    role="user",
                    text=(
                        "I have already searched and fetched these pages for you. "
                        "Read them first, and only search again if they are not enough.\n\n"
                        + "\n\n---\n\n".join(f"URL: {p.url}\n{p.content}" for p in seed_pages)
                    ),
                )
            )

        # ---- Phase A1: optional refinement --------------------------------
        for turn in range(limits.refinement_turns):
            # Withdraw search once the model has had its allowance and still
            # has not opened a page, so the remaining turns can only read.
            offered = [SEARCH_TOOL, FETCH_TOOL]
            if not visited_urls and searches >= limits.searches_before_fetch_forced:
                offered = [FETCH_TOOL]

            response = llm.generate(
                messages, system=system_prompt, tools=offered, temperature=0.3
            )

            if not response.tool_calls:
                transcript.append({"turn": turn, "action": "stopped", "text": response.text[:400]})
                break

            messages.append(Message(role="model", tool_calls=response.tool_calls))
            results: list[ToolResult] = []
            # A model will happily call a tool it used earlier even after that
            # tool stops being offered, so the gate is enforced here as well as
            # declared above. Checking the name alone silently reopened it.
            offered_names = {tool.name for tool in offered}

            for call in response.tool_calls:
                if call.name not in offered_names:
                    transcript.append(
                        {"turn": turn, "tool": call.name, "refused": "not offered this turn"}
                    )
                    results.append(
                        _tool_result(
                            call.id,
                            call.name,
                            {"error": f"{call.name} is unavailable; use {sorted(offered_names)}"},
                        )
                    )

                elif call.name == SEARCH_TOOL.name and searches < limits.max_searches:
                    searches += 1
                    raw_query = str(call.arguments.get("query", "")).strip()
                    query = _strip_gated_operators(raw_query, policy)
                    hits = [
                        h
                        for h in search_provider.search(
                            query, max_results=int(call.arguments.get("max_results") or 5)
                        )
                        if _is_readable(h.url, policy)
                    ]
                    candidate_urls.extend(h.url for h in hits if h.url not in candidate_urls)
                    entry: dict[str, Any] = {
                        "turn": turn,
                        "tool": "search",
                        "query": query,
                        "results": len(hits),
                    }
                    if query != raw_query:
                        entry["rewritten_from"] = raw_query
                    transcript.append(entry)
                    results.append(
                        _tool_result(
                            call.id,
                            call.name,
                            [{"title": h.title, "url": h.url, "snippet": h.snippet} for h in hits],
                        )
                    )

                elif call.name == FETCH_TOOL.name and fetches < limits.max_fetches:
                    urls = [str(u) for u in (call.arguments.get("urls") or []) if _is_readable(str(u), policy)][:5]
                    fetches += len(urls)
                    pages = fetch_provider.fetch(urls, max_chars=limits.page_char_budget)
                    # Only pages that came back are recorded as visited — a URL
                    # the fetcher could not render was not read, so citing it
                    # later must still fail validation.
                    visited_urls.update(p.url for p in pages)
                    transcript.append(
                        {
                            "turn": turn,
                            "tool": "fetch_page",
                            "requested": urls,
                            "retrieved": [p.url for p in pages],
                        }
                    )
                    results.append(
                        _tool_result(
                            call.id,
                            call.name,
                            [{"url": p.url, "content": p.content} for p in pages],
                        )
                    )

                else:
                    # Budget exhausted or unknown tool. Told to the model rather
                    # than raised, so it can wrap up instead of stalling.
                    transcript.append({"turn": turn, "tool": call.name, "skipped": "budget_exhausted"})
                    results.append(
                        _tool_result(call.id, call.name, {"error": "tool budget exhausted; summarise now"})
                    )

            messages.append(Message(role="user", tool_results=results))

        # ---- Phase A2: deterministic fallback ------------------------------
        # If the model spent its whole budget searching, read the top results
        # ourselves. Evidence the agent did not think to open is still
        # evidence, and this turns an empty run into a usable one.
        if not visited_urls and candidate_urls:
            pages = fetch_provider.fetch(candidate_urls[:limits.seed_fetch_count], max_chars=limits.page_char_budget)
            visited_urls.update(p.url for p in pages)
            transcript.append(
                {
                    "stage": "fallback_fetch",
                    "reason": "agent exhausted its turns without reading a page",
                    "retrieved": [p.url for p in pages],
                }
            )
            if pages:
                messages.append(
                    Message(
                        role="user",
                        text=(
                            "Here are the top search results, fetched for you:\n\n"
                            + "\n\n".join(f"URL: {p.url}\n{p.content}" for p in pages)
                        ),
                    )
                )

        # ---- Phase B: structured extraction -------------------------------
        if not visited_urls:
            raise ProviderError(
                "Discovery agent did not successfully read any page",
                details={"searches": searches, "fetch_attempts": fetches},
            )

        messages.append(Message(role="user", text=policy.prompts.extraction.format(limit=requested_count)))
        raw = llm.generate(
            messages, system=system_prompt, json_schema=EXTRACTION_JSON_SCHEMA, temperature=0.1
        )

        try:
            extraction = ExtractionResult.model_validate_json(raw.text)
        except ValidationError as exc:
            raise ProviderError(
                "Extraction output did not match the schema",
                details={"errors": exc.errors()[:5], "text": raw.text[:400]},
            ) from exc

        # ---- Phase C: business validation ---------------------------------
        outcome = validate_candidates(extraction.leads, visited_urls=visited_urls)
        transcript.append(
            {
                "stage": "validation",
                "extracted": len(extraction.leads),
                "accepted": len(outcome.accepted),
                "rejected": [{"lead": r.lead, "reason": r.reason, "detail": r.detail} for r in outcome.rejections],
                "stripped": [{"lead": s.lead, "reason": s.reason, "detail": s.detail} for s in outcome.strips],
            }
        )

        # ---- Phase D: persist ---------------------------------------------
        companies_created = 0
        leads_created = 0

        for candidate in outcome.accepted:
            company, created = _upsert_company(db, candidate, model=raw.model)
            companies_created += int(created)
            if _create_lead(db, company, candidate, run, model=raw.model, icp_owner_id=icp.owner_id):
                leads_created += 1

        run.status = DiscoveryRunStatus.COMPLETED
        run.companies_created = companies_created
        run.leads_created = leads_created
        run.leads_rejected = len(outcome.rejections)

    except Exception as exc:
        run.status = DiscoveryRunStatus.FAILED
        run.error = f"{type(exc).__name__}: {exc}"
        transcript.append({"stage": "error", "error": run.error})
        logger.exception("discovery run %s failed", run.id)

    run.completed_at = datetime.now(UTC)
    run.agent_log = {
        "transcript": transcript,
        "visited_urls": sorted(visited_urls),
        "searches": searches,
        "fetches": fetches,
    }
    db.flush()
    logger.info(
        "discovery %s %s: %d leads, %d rejected",
        run.id,
        run.status,
        run.leads_created,
        run.leads_rejected,
    )
    return run


def _upsert_company(db: Session, candidate: ExtractedLead, *, model: str) -> tuple[Company, bool]:
    """Find the company or create it. Matched on domain first, then name."""
    domain = (candidate.company_domain or "").strip().lower().removeprefix("www.") or None

    existing = None
    if domain:
        existing = db.scalar(select(Company).where(Company.domain == domain))
    if existing is None:
        existing = db.scalar(
            select(Company).where(func.lower(Company.name) == candidate.company_name.lower())
        )

    if existing is not None:
        # Backfill only. An established record is not overwritten by a later
        # run that happened to read a thinner page.
        for field, value in (
            ("domain", domain),
            ("industry", candidate.company_industry),
            ("region", candidate.company_region),
            ("country", candidate.company_country),
            ("employee_count", candidate.company_employee_count),
            ("description", candidate.company_description),
        ):
            if getattr(existing, field) is None and value is not None:
                setattr(existing, field, value)
        return existing, False

    company = Company(
        name=candidate.company_name,
        domain=domain,
        industry=candidate.company_industry,
        region=candidate.company_region,
        country=candidate.company_country,
        employee_count=candidate.company_employee_count,
        description=candidate.company_description,
        source_url=candidate.source_url,
        raw_data={"extracted_by": model, "extracted_at": datetime.now(UTC).isoformat()},
    )
    db.add(company)
    db.flush()
    return company, True


def _create_lead(
    db: Session, company: Company, candidate: ExtractedLead, run: DiscoveryRun,
    *, model: str, icp_owner_id=None,
) -> bool:
    """Create the lead unless it already exists. Returns whether it was new."""
    duplicate = db.scalar(
        select(Lead).where(
            Lead.company_id == company.id,
            func.lower(Lead.first_name) == candidate.first_name.lower(),
            func.coalesce(func.lower(Lead.last_name), "") == (candidate.last_name or "").lower(),
        )
    )
    if duplicate is not None:
        if duplicate.email is None and candidate.email:
            duplicate.email = candidate.email
        return False

    lead = Lead(
        company_id=company.id,
        discovery_run_id=run.id,
        # Inherited from whoever defined the ICP, so a discovered lead
        # lands in that salesperson's list rather than nobody's.
        owner_id=icp_owner_id,
        first_name=candidate.first_name,
        last_name=candidate.last_name,
        job_title=candidate.job_title,
        email=candidate.email,
        linkedin_url=candidate.linkedin_url,
        source_url=candidate.source_url,
        raw_data={
            # Carried forward verbatim: this is what the outreach grounding
            # check will later resolve `observed_signal_sentence` against.
            "observed_signal": (
                {"text": candidate.observed_signal, "source_url": candidate.signal_source_url}
                if candidate.observed_signal
                else None
            ),
            "extracted_by": model,
        },
    )
    db.add(lead)
    db.flush()
    apply_score(db, lead, reason="Lead discovered")
    return True
