"""
Bond Product Catalog — the available bond types and the rules that map deal
parameters to a structural variant.

Source: Nest Bond Use Case Manual, Ch.1 (M&A Acquisition Bonds), §6 "The Bond
Product Layer — Which Bond Types Qualify" and §7 (amortization/reserves/
covenants/optionality). This encodes the manual's variant catalog and the
eligibility logic so the structuring engine recommends a bond type rather than
defaulting to one.

Other use cases (construction, working capital, equipment, real estate) get
their own catalogs as those manual chapters are written; M&A is fully specified
here and is the first encoded use case.
"""
from __future__ import annotations


# ── M&A Acquisition Bond — structural variants (Use Case Manual §6) ──────────
MA_BOND_VARIANTS = [
    {
        "id": "taxable_senior_secured_term",
        "name": "Taxable Senior Secured Term Bond",
        "summary": "Single-tranche, taxable, senior secured by target assets + acquirer equity. The default workhorse.",
        "tenor_years": "5-10",
        "amortization": "12-24mo IO, then 1-3%/yr, balloon at maturity",
        "security": "first lien on all assets + equity pledge of acquirer",
        "buyer_pool": "HY bond funds, specialty credit, BDCs, insurance portfolios",
        "typical_rating": "B+ to BB-",
        "typical_sizing": "4-6x EBITDA senior",
        "is_default": True,
    },
    {
        "id": "senior_plus_subordinate",
        "name": "Senior Secured + Subordinate Tranche",
        "summary": "Adds a second-lien/unsecured tranche when senior leverage capacity can't cover the financing need.",
        "tenor_years": "senior 5-10; sub equal/slightly longer",
        "amortization": "senior per workhorse; sub bullet or back-loaded",
        "security": "senior first lien; sub second-lien/unsecured; inter-creditor agreement",
        "buyer_pool": "senior as above; sub to mezz/specialty credit/hedge funds",
        "typical_rating": "split-rated by tranche",
        "typical_sizing": "sub fills 0.5-2.0x additional EBITDA leverage",
        "is_default": False,
    },
    {
        "id": "cash_collateralized_lc",
        "name": "Cash-Collateralized LC Structure",
        "summary": "Sponsor cash collateralizes a bank LC; bond takes the LC bank's IG rating → IG pricing on a HY credit. Signature structure.",
        "tenor_years": "matched to hold",
        "amortization": "flexible — cash sits in collateral account earning market rates",
        "security": "Letter of Credit from IG bank, backed by sponsor cash collateral",
        "buyer_pool": "IG buyers (LC-wrapped)",
        "typical_rating": "A-1+/P-1 (≈AA+/AAA)",
        "typical_sizing": "bond principal ≤ deployable sponsor cash",
        "is_default": False,
    },
    {
        "id": "tax_exempt_acquisition",
        "name": "Tax-Exempt Acquisition Bond",
        "summary": "Where the target qualifies: 501(c)(3)→501(c)(3) (§145), §142 PAB facility, or §144(a) small-issue manufacturing.",
        "tenor_years": "long-dated",
        "amortization": "level debt service typical",
        "security": "per conduit/indenture; ongoing tax-exempt compliance",
        "buyer_pool": "tax-exempt / municipal buyers",
        "typical_rating": "varies; 150-250bps yield benefit vs taxable",
        "typical_sizing": "subject to volume cap (PAB) / $10M limit (§144a)",
        "is_default": False,
    },
    {
        "id": "delayed_draw",
        "name": "Delayed Draw Bond",
        "summary": "Committed financing for a platform + add-ons; draws down as add-ons close. For buy-and-build strategies.",
        "tenor_years": "5-10; draw window 24-36mo",
        "amortization": "per workhorse on drawn balance; commitment fee 25-50bps on undrawn",
        "security": "first lien; add-on draws subject to coverage + equity tests",
        "buyer_pool": "HY/specialty credit comfortable with delayed-draw",
        "typical_rating": "B+ to BB-",
        "typical_sizing": "sized above platform deal for committed add-on capacity",
        "is_default": False,
    },
    {
        "id": "add_on_refi_mechanic",
        "name": "Acquisition Bond w/ Add-On Refinancing Mechanic",
        "summary": "Initial platform bond permits additional issuance under the same indenture for add-ons. Pay interest only on deployed principal.",
        "tenor_years": "5-10",
        "amortization": "per workhorse; each add-on is a discrete issuance",
        "security": "shared security/indenture across add-on issuances",
        "buyer_pool": "HY/specialty credit",
        "typical_rating": "B+ to BB-",
        "typical_sizing": "platform-only initial; add-ons sized to need",
        "is_default": False,
    },
]

MA_VARIANTS_BY_ID = {v["id"]: v for v in MA_BOND_VARIANTS}


def recommend_ma_variant(deal: dict) -> dict:
    """Map deal parameters to the M&A bond variant(s) that fit (Use Case Manual §6).

    Returns the primary recommendation plus any alternatives unlocked by the
    deal's profile, each with the rationale that triggered it. When a defining
    parameter is absent, the variant is surfaced as "available if <condition>"
    rather than silently dropped — so the banker sees the full menu.
    """
    sponsor_type = (deal.get("sponsor_type") or "").lower()
    sector = (deal.get("sector") or "").lower()
    deployable_cash = float(deal.get("deployable_cash") or 0)
    bond_amount = float(deal.get("bond_amount") or deal.get("project_size") or 0)
    target_501c3 = bool(deal.get("target_501c3") or sector in ("hospitals", "senior_living") and deal.get("nonprofit"))
    add_on_strategy = bool(deal.get("add_on_strategy") or deal.get("buy_and_build"))
    leverage_need = float(deal.get("leverage") or 0)
    senior_capacity = float(deal.get("senior_leverage_capacity") or 5.0)

    matches: list[dict] = []

    # Cash-collateralized LC — deployable cash >= principal (or a cash-rich sponsor type).
    if deployable_cash and bond_amount and deployable_cash >= bond_amount:
        matches.append({**MA_VARIANTS_BY_ID["cash_collateralized_lc"], "rationale": "deployable sponsor cash ≥ bond principal — LC wrap unlocks IG pricing"})
    elif sponsor_type in ("family_office", "pe_firm"):
        matches.append({**MA_VARIANTS_BY_ID["cash_collateralized_lc"], "rationale": f"available if {sponsor_type.replace('_',' ')} commits cash collateral ≈ principal", "conditional": True})

    # Tax-exempt — qualifying nonprofit / facility target.
    if target_501c3:
        matches.append({**MA_VARIANTS_BY_ID["tax_exempt_acquisition"], "rationale": "qualifying 501(c)(3)/PAB target — tax-exempt treatment available (150-250bps benefit)"})

    # Buy-and-build — delayed draw or add-on refi.
    if add_on_strategy:
        matches.append({**MA_VARIANTS_BY_ID["delayed_draw"], "rationale": "buy-and-build strategy — committed add-on capacity"})
        matches.append({**MA_VARIANTS_BY_ID["add_on_refi_mechanic"], "rationale": "alternative to delayed draw for fewer/larger add-ons"})

    # Leverage gap beyond senior capacity — add a subordinate tranche.
    if leverage_need and leverage_need > senior_capacity:
        matches.append({**MA_VARIANTS_BY_ID["senior_plus_subordinate"], "rationale": f"leverage need {leverage_need:.1f}x exceeds senior capacity {senior_capacity:.1f}x — subordinate tranche fills the gap"})

    # Primary recommendation: highest-value fit, else the workhorse default.
    # Priority order: LC (IG pricing) > tax-exempt > sub-tranche > delayed draw > default.
    priority = ["cash_collateralized_lc", "tax_exempt_acquisition", "senior_plus_subordinate", "delayed_draw", "add_on_refi_mechanic"]
    primary = None
    for pid in priority:
        cand = next((m for m in matches if m["id"] == pid and not m.get("conditional")), None)
        if cand:
            primary = cand
            break
    if not primary:
        primary = {**MA_VARIANTS_BY_ID["taxable_senior_secured_term"], "rationale": "default workhorse — no parameter triggers a specialized variant"}

    alternatives = [m for m in matches if m["id"] != primary["id"]]
    return {
        "use_case": "ma_acquisition",
        "primary": primary,
        "alternatives": alternatives,
        "catalog": [v["id"] for v in MA_BOND_VARIANTS],
    }
