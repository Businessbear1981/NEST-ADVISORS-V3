"""
Structuring Desk — track router.

Not every deal is a bond. The Structuring Desk routes each deal to a financing
track based on the deal input and the preflight interview, then applies that
track's structuring profile, document package, and credit-memo type. Bond is one
track (handled by the EMMA-comp + bond-product engine in deal_flow); the others
are conventional (traditional commercial mortgage / term loan), private equity,
family office, and bridge.

Every track's credit package is built to audit grade using conventional
commercial-credit / investment-banking guidelines, so handoff to an external
auditor is a review rather than a rebuild.
"""
from __future__ import annotations


# Deal-input deal_type → default track. The interview can override (see classify_track).
_DEAL_TYPE_TRACK = {
    "ma_acquisition": "bond",          # bond is lead product; LC/PE variants handled in bond_products
    "construction": "bond",
    "refunding": "bond",
    "real_estate": "conventional",     # stabilized RE acquisition → traditional mortgage
    "working_capital": "conventional",
    "ci_lending": "conventional",
    "equipment": "conventional",
    "equity_raise": "private_equity",
    "mezzanine": "private_equity",
    "bridge": "bridge",
    "general_advisory": "conventional",
}

TRACKS = {
    "bond": {"label": "Bond", "memo_type": "credit_memo", "desk": "Bond Desk"},
    "conventional": {"label": "Conventional Debt", "memo_type": "credit_memo", "desk": "Structuring Desk"},
    "private_equity": {"label": "Private Equity", "memo_type": "investor_teaser", "desk": "Structuring Desk"},
    "family_office": {"label": "Family Office", "memo_type": "executive_summary", "desk": "Structuring Desk"},
    "bridge": {"label": "Bridge", "memo_type": "term_sheet_cover", "desk": "Structuring Desk"},
}


def classify_track(deal: dict) -> dict:
    """Choose the financing track from deal input + interview signals.

    Input deal_type sets the default; explicit interview/intent signals override.
    Returns {track, rationale, source}.
    """
    deal_type = (deal.get("deal_type") or "ma_acquisition").lower()
    sponsor_type = (deal.get("sponsor_type") or "").lower()
    intent = (deal.get("financing_intent") or deal.get("requested_product") or "").lower()
    interview = {k.lower(): str(v).lower() for k, v in (deal.get("interview_answers") or {}).items()}
    blob = " ".join(interview.values())

    # 1. Explicit request in the input — e.g. "we're asking for bond lending" → straight to bond.
    if intent:
        if "bond" in intent:
            return {"track": "bond", "rationale": f"input requested bond financing ('{intent}')", "source": "input"}
        if any(k in intent for k in ("mortgage", "conventional", "bank", "term loan")):
            return {"track": "conventional", "rationale": f"input requested conventional financing ('{intent}')", "source": "input"}
        if "bridge" in intent:
            return {"track": "bridge", "rationale": f"input requested bridge financing ('{intent}')", "source": "input"}
        if any(k in intent for k in ("equity", "pe", "private equity")):
            return {"track": "private_equity", "rationale": f"input requested equity ('{intent}')", "source": "input"}

    # 2. Interview signals override the deal-type default — "this is a regular down-the-middle mortgage".
    if any(k in blob for k in ("down the middle", "conventional mortgage", "standard mortgage", "bank loan", "vanilla")):
        return {"track": "conventional", "rationale": "interview indicates a conventional mortgage / bank loan", "source": "interview"}
    if "bridge" in blob or "short-term" in blob:
        return {"track": "bridge", "rationale": "interview indicates short-term bridge financing", "source": "interview"}

    # 3. Sponsor type nudges equity tracks for equity raises.
    base = _DEAL_TYPE_TRACK.get(deal_type, "conventional")
    if base == "private_equity" and sponsor_type == "family_office":
        return {"track": "family_office", "rationale": "equity raise sponsored by a family office", "source": "deal_type+sponsor"}

    return {"track": base, "rationale": f"default track for deal_type '{deal_type}'", "source": "deal_type"}


def _conventional_docs() -> list[dict]:
    """Traditional commercial mortgage / term-loan package — built to audit grade."""
    return [
        {"key": "audited_financials", "label": "Audited Financial Statements (2-3 yr)", "required": True, "reason": "audit-grade credit baseline"},
        {"key": "interim_financials", "label": "Interim / YTD Financials", "required": True, "reason": "current performance"},
        {"key": "tax_returns", "label": "Business + Personal Tax Returns (3 yr)", "required": True, "reason": "income verification"},
        {"key": "personal_financial_statement", "label": "Personal Financial Statement (guarantors)", "required": True, "reason": "recourse / guaranty"},
        {"key": "rent_roll", "label": "Rent Roll + Lease Abstracts", "required": True, "reason": "income property cash flow"},
        {"key": "appraisal", "label": "MAI Appraisal", "required": True, "reason": "LTV / collateral value"},
        {"key": "environmental", "label": "Phase I Environmental", "required": True, "reason": "collateral risk"},
        {"key": "property_condition", "label": "Property Condition Report", "required": True, "reason": "capex / deferred maintenance"},
        {"key": "title", "label": "Title Commitment + Survey", "required": True, "reason": "lien position"},
        {"key": "sources_and_uses", "label": "Sources & Uses", "required": True, "reason": "proceeds allocation"},
        {"key": "debt_schedule", "label": "Existing Debt Schedule", "required": True, "reason": "global cash flow / leverage"},
    ]


def _equity_docs() -> list[dict]:
    return [
        {"key": "audited_financials", "label": "Audited Financial Statements (3 yr)", "required": True, "reason": "audit-grade diligence"},
        {"key": "cap_table", "label": "Capitalization Table", "required": True, "reason": "ownership / dilution"},
        {"key": "proforma", "label": "Pro Forma / 5-yr Model", "required": True, "reason": "returns underwriting"},
        {"key": "quality_of_earnings", "label": "Quality of Earnings", "required": True, "reason": "adjusted EBITDA normalization"},
        {"key": "management_deck", "label": "Management Presentation / CIM", "required": True, "reason": "thesis + team"},
        {"key": "market_study", "label": "Market / TAM Analysis", "required": False, "reason": "growth thesis"},
        {"key": "legal_diligence", "label": "Legal Diligence (contracts, IP, litigation)", "required": True, "reason": "diligence"},
    ]


def _bridge_docs() -> list[dict]:
    return [
        {"key": "term_sheet", "label": "Bridge Term Sheet", "required": True, "reason": "structure"},
        {"key": "takeout_evidence", "label": "Takeout / Exit Evidence (perm commitment, sale contract)", "required": True, "reason": "repayment source"},
        {"key": "appraisal", "label": "Appraisal / Valuation", "required": True, "reason": "collateral value"},
        {"key": "audited_financials", "label": "Financial Statements", "required": True, "reason": "sponsor capacity"},
        {"key": "sources_and_uses", "label": "Sources & Uses", "required": True, "reason": "use of bridge proceeds"},
    ]


def non_bond_profile(deal: dict, track: str) -> dict:
    """Structuring profile for a non-bond track — structure, docs, memo, audit-grade package."""
    sector = deal.get("sector", "")
    grade = deal.get("credit_grade", "BBB")
    meta = TRACKS.get(track, TRACKS["conventional"])

    if track == "conventional":
        structure = {
            "instrument": "Conventional Commercial Mortgage / Term Loan",
            "amortization": "25-30yr amortizing, 5-10yr term/balloon",
            "pricing_basis": "SOFR + spread or fixed to comparable bank index",
            "ltv_max": 0.75, "dscr_min": 1.25,
            "recourse": "full or partial guaranty",
            "covenants": {"dscr_min": 1.25, "ltv_max": 0.75, "reporting": "annual audited + quarterly"},
        }
        docs = _conventional_docs()
    elif track in ("private_equity", "family_office"):
        structure = {
            "instrument": "Equity / Preferred" if track == "private_equity" else "Family Office Direct Equity",
            "structure": "common + preferred, board/governance terms",
            "return_target": "IRR / MOIC underwriting",
            "horizon_years": 5,
        }
        docs = _equity_docs()
    elif track == "bridge":
        structure = {
            "instrument": "Bridge Loan",
            "tenor_months": 12, "extension_options": "6+6",
            "pricing_basis": "SOFR + spread, IO",
            "exit": "perm financing or asset sale (takeout required)",
            "ltv_max": 0.70,
        }
        docs = _bridge_docs()
    else:
        structure = {"instrument": meta["label"]}
        docs = _conventional_docs()

    return {
        "track": track,
        "track_label": meta["label"],
        "desk": meta["desk"],
        "instrument": structure.get("instrument"),
        "structure": structure,
        "document_checklist": docs,
        "credit_memo": {
            "memo_type": meta["memo_type"],
            "standard": "conventional commercial credit (investment-banking guidelines)",
            "grade": "audit",  # built to full audit level for clean external-auditor handoff
            "auditor_handoff_ready": True,
            "audit_endpoints": ["/api/audit/run", "/api/audit/sources-uses", "/api/audit/assumptions"],
        },
    }
