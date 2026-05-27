"""
NEST Deal Flow Orchestrator — wires desks together.

A deal enters at BD/intake and flows:
BD → Bond Desk (sizing) → Credit UW (memo + grade) → Rating (prediction)
→ Structuring (terms) → Enhancement (if needed) → Documents (package)
→ Placement (marketing) → Closing → Operations (admin) → Surveillance

Each transition carries specific data. This orchestrator manages
what data flows between desks and validates completeness.
"""
from __future__ import annotations
from datetime import datetime


# Investment-grade floor — anything below these is sub-IG and a candidate for
# credit enhancement to lift it back into IG territory.
_SUB_IG_RATINGS = {
    "BB+", "BB", "BB-", "B+", "B", "B-", "CCC+", "CCC", "CCC-", "CC", "C", "D",
    "BA1", "BA2", "BA3", "B1", "B2", "B3", "CAA1", "CAA2", "CAA3", "CA",
}


def _is_sub_ig(rating: str) -> bool:
    return (rating or "").upper().replace(" ", "") in _SUB_IG_RATINGS


def _most_common(values: list, fallback):
    counts: dict = {}
    for v in values:
        if v:
            counts[v] = counts.get(v, 0) + 1
    return max(counts, key=counts.get) if counts else fallback


def _document_checklist(sector: str, tax_status: str, security_type: str, enhancement: str) -> list[dict]:
    """Derive the required document package from the instrument's profile.

    Modeled on what a comparable completed bond required — grounded in the
    instrument type (tax status, security, sector, enhancement), not invented.
    """
    docs = [
        {"key": "audited_financials", "label": "Audited Financial Statements (2-3 yr)", "required": True, "reason": "credit baseline"},
        {"key": "proforma", "label": "Pro Forma / Feasibility Projections", "required": True, "reason": "forward debt service coverage"},
        {"key": "sources_and_uses", "label": "Sources & Uses", "required": True, "reason": "proceeds allocation"},
        {"key": "officer_certificate", "label": "Officer's Certificate / Covenant Compliance", "required": True, "reason": "covenant baseline"},
        {"key": "official_statement", "label": "Preliminary Official Statement", "required": True, "reason": "offering disclosure"},
        {"key": "trust_indenture", "label": "Trust Indenture", "required": True, "reason": "defines trustee duties, flow of funds, call mechanics"},
        {"key": "continuing_disclosure", "label": "Continuing Disclosure Agreement", "required": True, "reason": "SEC Rule 15c2-12"},
    ]
    if tax_status == "tax_exempt":
        docs += [
            {"key": "tefra_hearing", "label": "TEFRA Hearing Record", "required": True, "reason": "tax-exempt public approval"},
            {"key": "tax_opinion", "label": "Bond Counsel Tax Opinion", "required": True, "reason": "tax-exempt status"},
            {"key": "form_8038", "label": "IRS Form 8038", "required": True, "reason": "tax-exempt issuance filing"},
        ]
    if security_type == "pab_501c3":
        docs.append({"key": "501c3_determination", "label": "IRS 501(c)(3) Determination Letter", "required": True, "reason": "qualified borrower"})
    if sector in ("senior_living", "hospitals"):
        docs += [
            {"key": "feasibility_study", "label": "Market / Feasibility Study", "required": True, "reason": f"{sector.replace('_',' ')} demand + absorption"},
            {"key": "appraisal", "label": "Appraisal", "required": True, "reason": "collateral value"},
        ]
    if sector == "senior_living":
        docs.append({"key": "census_unit_mix", "label": "Census / Unit Mix Schedule", "required": False, "reason": "occupancy detail"})
    if enhancement and enhancement not in ("none", None):
        docs.append({"key": "enhancement_commitment", "label": f"{enhancement.replace('_',' ').title()} Commitment Letter", "required": True, "reason": "credit enhancement"})
    return docs


class DealFlow:
    """Orchestrates deal lifecycle across desks."""

    def __init__(self):
        from services.intelligence_engine import IntelligenceEngine
        self.intel = IntelligenceEngine()

    def run_intake(self, deal: dict) -> dict:
        """Stage 1: BD intake → Bond Desk. Runs sizing, enriches deal.

        Handles all deal types: M&A, construction, working capital, equipment, real estate.
        Each type returns different fields — normalize into a common deal structure.
        """
        sizing = self.intel.size_bond(deal)
        deal_type = deal.get("deal_type", "ma_acquisition")

        # Extract bond amount from whichever field the sizing engine returns
        deal["bond_amount"] = (
            sizing.get("capital_structure", {}).get("senior_bond", 0) or
            sizing.get("bond_amount", 0) or
            deal.get("bond_amount", 0)
        )
        deal["enterprise_value"] = sizing.get("valuation", {}).get("enterprise_value", 0)

        # DSCR: use from sizing if available, otherwise preserve what was passed in
        sized_dscr = sizing.get("credit", {}).get("dscr", 0)
        deal["dscr"] = sized_dscr if sized_dscr > 0 else deal.get("dscr", 0)

        # Credit grade: use from sizing if available
        sized_grade = sizing.get("credit", {}).get("grade", "")
        deal["credit_grade"] = sized_grade if sized_grade else self.intel._grade_credit(
            deal.get("dscr", 1.0), deal.get("leverage", 5.0)
        )

        # Leverage: from sizing or preserve passed value
        deal["leverage"] = (
            sizing.get("capital_structure", {}).get("total_leverage", 0) or
            deal.get("leverage", 0)
        )

        deal["sources_and_uses"] = sizing.get("sources_and_uses", {})
        deal["readiness_flags"] = sizing.get("readiness_flags", [])
        deal["pricing"] = sizing.get("bond_structure", {})
        deal["reserves"] = sizing.get("reserves", {})
        deal["fees"] = sizing.get("fees", {})
        deal["stage"] = "intake_complete"
        deal.setdefault("desk_outputs", {})["bond_desk"] = sizing
        deal["stage_timestamp"] = datetime.utcnow().isoformat()
        return deal

    def run_credit(self, deal: dict) -> dict:
        """Stage 2: Credit Underwriting. Policy check + credit memo."""
        uw_result = self.intel.underwrite({
            "dscr": deal.get("dscr", 0),
            "total_leverage": deal.get("leverage", 0),
            "equity_pct": deal.get("equity_pct", 0),
            "sponsor_experience_years": deal.get("sponsor_experience_years", 0),
            "deal_type": deal.get("deal_type", "stabilized"),
        })
        deal["credit_policy_check"] = uw_result
        deal.setdefault("desk_outputs", {})["credit_underwriting"] = uw_result

        try:
            from agents.credit_memo_agent import CreditMemoAgent
            memo = CreditMemoAgent().generate_memo(deal)
            deal["credit_memo"] = memo
            deal["desk_outputs"]["credit_underwriting"]["memo"] = memo
        except Exception:
            deal["credit_memo"] = None

        deal["stage"] = "credit_complete"
        deal["stage_timestamp"] = datetime.utcnow().isoformat()
        return deal

    def run_rating(self, deal: dict) -> dict:
        """Stage 3: Rating Desk. Mirror Agent predictions + submission prep."""
        try:
            from agents.moodys_mirror import MoodysMirrorAgent
            from agents.sp_mirror import SPMirrorAgent

            rating_input = {
                "sector": deal.get("sector", "corporate"),
                "dscr": deal.get("dscr", 1.0),
                "leverage": deal.get("leverage", 5.0),
                "revenue": deal.get("revenue", 0),
                "ebitda": deal.get("ebitda", 0),
                "equity_pct": deal.get("equity_pct", 0.20),
                "enhancement": deal.get("enhancement", "none"),
                "management_quality": deal.get("management_quality", "adequate"),
                "market_position": deal.get("market_position", "satisfactory"),
                "revenue_diversity": deal.get("revenue_diversity", "moderate"),
                "days_cash_on_hand": deal.get("days_cash_on_hand", 90),
            }

            moodys = MoodysMirrorAgent()
            sp = SPMirrorAgent()

            m_scorecard = moodys.scorecard(rating_input)
            sp_brp = sp.business_risk_profile(rating_input)
            sp_frp = sp.financial_risk_profile(rating_input)

            deal["predicted_moodys"] = m_scorecard["predicted_rating"]
            deal["moodys_scorecard"] = m_scorecard
            deal["sp_assessment"] = {"business_risk": sp_brp, "financial_risk": sp_frp}
            deal["structural_levers"] = moodys.identify_levers(rating_input, m_scorecard)
            deal.setdefault("desk_outputs", {})["rating"] = {
                "moodys": m_scorecard,
                "sp": {"brp": sp_brp, "frp": sp_frp},
                "predicted_moodys": deal["predicted_moodys"],
            }
        except Exception as e:
            deal["rating_error"] = str(e)

        deal["stage"] = "rating_complete"
        deal["stage_timestamp"] = datetime.utcnow().isoformat()
        return deal

    def run_structuring(self, deal: dict) -> dict:
        """Stage 4: Structuring. Derive terms from EMMA comparables, refined by the rating.

        Tiered match:
          1. tight comps  — same sector, similar size, same rating band (near-exact)
          2. similar comps — same sector, wider size band, any rating
          3. static Bible  — Operating Framework defaults when EMMA has no comps
                             (expected for M&A/corporate — EMMA is municipal/revenue bonds)

        The chosen path is recorded in `match_quality` so the structure is transparent
        about whether it was learned from funded deals or fell back to framework defaults.
        """
        sector = deal.get("sector", "corporate_ma")
        deal_type = deal.get("deal_type", "ma_acquisition")
        predicted = deal.get("predicted_moodys") or deal.get("credit_grade") or ""

        from services.emma_engine import EMMAEngine, PARSED_BONDS
        from services.emma_seed_data import seed_emma_database
        if not PARSED_BONDS:
            seed_emma_database()  # load the comp corpus so aggregation/comps have data
        emma = EMMAEngine()

        par = float(deal.get("bond_amount") or deal.get("project_size") or 0)
        inf = float("inf")
        tight = (par * 0.6, par * 1.6) if par else (0, inf)
        wide = (par * 0.3, par * 3.0) if par else (0, inf)

        # Tier 1 — near-exact: sector + similar size + same rating.
        comps = emma.find_comps(sector=sector, min_par=tight[0], max_par=tight[1], rating=predicted, limit=5)
        match_quality = "exact_comp"
        if not comps:
            # Tier 2 — similar: sector + wider size band, any rating.
            comps = emma.find_comps(sector=sector, min_par=wide[0], max_par=wide[1], limit=8)
            match_quality = "similar_comp"

        # Bible / Operating Framework static base — full structural scaffold for the sector.
        base = emma._static_template(sector).get("template", {})

        if comps:
            # Learn the structural pattern from the comparable funded deals.
            bond_type = _most_common([c.get("bond_type") for c in comps], base.get("bond_type") or base.get("typical_amortization"))
            amortization = _most_common([c.get("amortization") for c in comps], base.get("typical_amortization"))
            tax_status = _most_common([c.get("tax_status") for c in comps], base.get("typical_tax_status"))
            security_type = _most_common([c.get("security_type") for c in comps], base.get("security_type"))
            enhancement = _most_common([(c.get("enhancement") or {}).get("type") for c in comps], base.get("typical_enhancement"))
        else:
            # Tier 3 — no EMMA comps (expected for M&A/corporate): use Bible defaults.
            match_quality = "static_bible"
            bond_type = base.get("bond_type") or base.get("typical_amortization")
            amortization = base.get("typical_amortization")
            tax_status = base.get("typical_tax_status")
            security_type = base.get("security_type")
            enhancement = base.get("typical_enhancement")

        # Grade-aware covenants, merged with the comp/Bible covenant pattern.
        covenant_package = self.intel.build_covenant_package(deal_type, deal.get("credit_grade", "BBB"), sector)
        covenant_package = {**base.get("covenant_package", {}), **(covenant_package or {})}

        # Enhancement decision: lift sub-IG deals toward IG with credit enhancement
        # (NEST model defaults to Hylant surety when none is indicated).
        enhancement_rationale = "matched comparable structure"
        if _is_sub_ig(predicted):
            if not enhancement or enhancement == "none":
                enhancement = "surety"
            enhancement_rationale = f"sub-IG ({predicted}) — enhancement applied to target investment grade"

        # Process blueprint — structure the deal around a completed comparable bond:
        # who ran it (counterparties) and what documents it required.
        top = comps[0] if comps else {}
        process_blueprint = {
            "modeled_on": top.get("borrower") if comps else "Operating Framework defaults",
            "recommended_counterparties": top.get("counterparties", {}),
            "document_checklist": _document_checklist(sector, tax_status, security_type, enhancement),
            "call_mechanics": (top.get("call_schedule") if comps else base.get("call_schedule")) or {},
        }

        structure = {
            "process_blueprint": process_blueprint,
            "bond_type": bond_type,
            "amortization": amortization,
            "tax_status": tax_status,
            "security_type": security_type,
            "enhancement": enhancement,
            "enhancement_rationale": enhancement_rationale,
            "call_schedule": base.get("call_schedule", {"nc_period_years": 10, "par_call_after": True}),
            "maturity_years": base.get("maturity_years", deal.get("tenor_years", 30)),
            "coupon_guidance": base.get("coupon_range", {}),
            "reserves": base.get("reserves", {}),
            "covenant_package": covenant_package,
            "match_quality": match_quality,
            "derived_from": {
                "method": "emma_comps+rating",
                "sector": sector,
                "predicted_rating": predicted,
                "par_reference": par,
                "comp_sample_size": len(comps),
                "comps": [
                    {
                        "borrower": c.get("borrower"),
                        "par_amount": c.get("par_amount"),
                        "bond_type": c.get("bond_type"),
                        "amortization": c.get("amortization"),
                        "enhancement": (c.get("enhancement") or {}).get("type"),
                        "ratings": c.get("ratings"),
                    }
                    for c in comps
                ],
            },
        }

        deal["covenant_package"] = covenant_package
        deal["structure"] = structure
        deal.setdefault("desk_outputs", {})["structuring"] = structure
        deal["stage"] = "structuring_complete"
        deal["stage_timestamp"] = datetime.utcnow().isoformat()
        return deal

    def run_full_pipeline(self, deal: dict) -> dict:
        """Run the complete deal through all desks in sequence."""
        deal = self.run_intake(deal)
        deal = self.run_credit(deal)
        deal = self.run_rating(deal)
        deal = self.run_structuring(deal)
        deal["stage"] = "pipeline_complete"
        deal["pipeline_summary"] = {
            "bond_amount": deal.get("bond_amount"),
            "credit_grade": deal.get("credit_grade"),
            "predicted_moodys": deal.get("predicted_moodys"),
            "dscr": deal.get("dscr"),
            "leverage": deal.get("leverage"),
            "desks_completed": list(deal.get("desk_outputs", {}).keys()),
        }
        deal["stage_timestamp"] = datetime.utcnow().isoformat()
        return deal
