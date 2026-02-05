# app/routes/reports_pdf.py
"""
Deep-Dive Infographic PDF Generator.
Engine: Playwright (Chromium)
Features: CSS Grid, Flexbox, Shadows, Gradients, High-DPI rendering.
"""

from flask import Blueprint, request, jsonify, send_file
from app.middleware.auth import requires_auth
from app.database.mongo import results_coll, ideas_coll, generated_reports_coll, users_coll
from app.utils.validators import parse_oid
from app.utils.id_helpers import ids_match
from datetime import datetime, timezone
import io
import logging

# Playwright Import
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logging.warning("Playwright not installed. Run: pip install playwright && playwright install chromium")

logger = logging.getLogger(__name__)
reports_pdf_bp = Blueprint("reports_pdf", __name__, url_prefix="/api/reports")


# ---------------------------- Helpers ----------------------------

def safe_get(data, *keys, default=""):
    result = data
    for key in keys:
        if isinstance(result, dict):
            result = result.get(key, {})
        else:
            return default
    return result if result not in (None, {}, []) else default

def get_risk_color(severity):
    s = str(severity or "").upper()
    if s == "CRITICAL": return "#dc2626"
    if s == "HIGH": return "#ef4444"
    if s == "MEDIUM": return "#f59e0b"
    if s == "LOW": return "#16a34a"
    return "#6b7280"

def render_list(items):
    if not items: return ""
    lis = "".join(f"<li>{item}</li>" for item in items)
    return f"<ul>{lis}</ul>"

# ---------------------------- HTML Builders ----------------------------

def build_business_case_html(bc):
    if not isinstance(bc, dict) or not bc:
        return '<div class="empty-state">Business case data not available.</div>'

    title = bc.get("title", "Business Case")
    exec_summary = bc.get("executiveSummary", "")

    # Data Extraction
    big_idea = bc.get("theBigIdea", {})
    solution = big_idea.get("solution", {})
    customer = bc.get("theCustomer", {})
    magic = bc.get("theMagic", {})
    biz_model = bc.get("businessModel", {})
    path = bc.get("pathForward", {})
    
    html = []

    # Section Header
    html.append(f"""
    <div class="section-header border-blue">
        <h2 class="text-blue">01. Business Case</h2>
        <div class="sub-title">{title}</div>
    </div>
    """)

    # Exec Summary
    html.append(f"""
    <div class="card bg-blue-light mb-4">
        <h4 class="text-blue uppercase">Executive Summary</h4>
        <p>{exec_summary}</p>
    </div>
    """)

    # Grid: Problem & Mission
    html.append(f"""
    <div class="grid-2 mb-4">
        <div class="card">
            <h4 class="text-blue uppercase">The Problem</h4>
            <p>{big_idea.get('problem', '')}</p>
        </div>
        <div class="card">
            <h4 class="text-blue uppercase">The Mission</h4>
            <p>{big_idea.get('mission', '')}</p>
        </div>
    </div>
    """)

    # Solution & Features
    html.append(f"""
    <div class="card mb-4 shadow-hover">
        <h4 class="text-blue uppercase">The Solution</h4>
        <p class="mb-2">{solution.get('overview', '')}</p>
        <div class="feature-chips">
            <strong>Key Features:</strong>
            {render_list(solution.get('keyFeatures', []))}
        </div>
        <div class="alert-box mt-3 border-blue">
            <strong>💎 Value Proposition:</strong> {big_idea.get('valueProposition', '')}
        </div>
    </div>
    """)

    # Target Market
    market = customer.get("targetMarket", [])
    if market:
        html.append('<h3 class="section-title">Target Market</h3>')
        market_html = ""
        for seg in market:
            market_html += f"""
            <div class="card mb-3 no-break">
                <div class="flex-row justify-between mb-2">
                    <strong class="text-lg">{seg.get('segment')}</strong>
                </div>
                <p>{seg.get('description')}</p>
                <div class="grid-2 mt-2 text-sm bg-gray-50 p-2 rounded">
                    <div><strong>😟 Pain Points:</strong><br>{seg.get('painPoints')}</div>
                    <div><strong>✅ How We Help:</strong><br>{seg.get('howWeHelp')}</div>
                </div>
            </div>
            """
        html.append(market_html)

    # Market Stats
    html.append(f"""
    <div class="grid-2 mb-4">
        <div class="card bg-gray-50">
            <h5 class="uppercase text-muted">Market Strategy</h5>
            <p>{customer.get('marketStrategy', '')}</p>
        </div>
        <div class="card bg-gray-50">
            <h5 class="uppercase text-muted">Market Size</h5>
            <p class="text-xl font-bold text-blue">{customer.get('marketSize', '')}</p>
        </div>
    </div>
    """)

    # Comparison
    comp = magic.get("comparison", {})
    html.append(f"""
    <h3 class="section-title">Competitive Landscape</h3>
    <div class="comparison-grid mb-4">
        <div class="comp-col">
            <div class="comp-header">Traditional Approach</div>
            <div class="comp-body">{comp.get('traditionalApproach', '-')}</div>
        </div>
        <div class="comp-col highlight">
            <div class="comp-header">Our Approach</div>
            <div class="comp-body">{comp.get('ourApproach', '-')}</div>
        </div>
        <div class="comp-col">
            <div class="comp-header">Why It Matters</div>
            <div class="comp-body">{comp.get('whyItMatters', '-')}</div>
        </div>
    </div>
    """)

    # Business Model
    html.append(f"""
    <h3 class="section-title">Business Model</h3>
    <div class="card mb-4">
        <div class="grid-3">
            <div>
                <h5 class="uppercase text-muted">Revenue Model</h5>
                <p>{biz_model.get('revenueModel', '')}</p>
            </div>
            <div>
                <h5 class="uppercase text-muted">Unit Economics</h5>
                <p>{biz_model.get('unitEconomics', '')}</p>
            </div>
            <div>
                <h5 class="uppercase text-muted">Financial Outlook</h5>
                <p>{biz_model.get('financialProjections', '')}</p>
            </div>
        </div>
        <div class="mt-3 pt-3 border-t">
            <strong>Revenue Streams:</strong>
            <ul class="compact-list">
                {"".join(f"<li><strong>{s.get('stream')}:</strong> {s.get('description')}</li>" for s in biz_model.get('revenueStreams', []))}
            </ul>
        </div>
    </div>
    """)

    return "\n".join(html)


def build_risk_assessment_html(ra):
    if not isinstance(ra, dict) or not ra:
        return '<div class="empty-state">Risk data not available.</div>'

    title = ra.get("title", "Risk Assessment")
    exec_summary = ra.get("executiveSummary", "")
    overall = ra.get("overallRiskProfile", {})
    
    # Flatten Risks
    cats = ra.get("riskCategories", {})
    all_risks = []
    for key, val in cats.items():
        if isinstance(val, list): all_risks.extend(val)

    mitigation = ra.get("prioritizedMitigation", [])

    html = []

    # Header
    html.append(f"""
    <div class="page-break"></div>
    <div class="section-header border-red">
        <h2 class="text-red">02. Risk Assessment</h2>
        <div class="sub-title">{title}</div>
    </div>
    """)

    # Exec Summary & Profile
    level_color = get_risk_color(overall.get('level'))
    html.append(f"""
    <div class="card bg-red-light mb-4">
        <h4 class="text-red uppercase">Executive Summary</h4>
        <p>{exec_summary}</p>
    </div>
    
    <div class="card mb-4 flex-row items-center border-l-thick" style="border-left-color: {level_color}">
        <div class="mr-4">
            <h5 class="uppercase text-muted mb-1">Overall Risk Level</h5>
            <div class="text-2xl font-bold" style="color: {level_color}">{overall.get('level', 'UNKNOWN')}</div>
        </div>
        <div class="pl-4 border-l">
            <p>{overall.get('explanation')}</p>
        </div>
    </div>
    """)

    # Detailed Risks
    if all_risks:
        html.append('<h3 class="section-title">Detailed Risk Register</h3>')
        for risk in all_risks:
            sev_color = get_risk_color(risk.get("severity"))
            html.append(f"""
            <div class="card mb-3 no-break risk-card" style="border-top: 4px solid {sev_color}">
                <div class="flex-row justify-between mb-2">
                    <strong class="text-lg" style="color: {sev_color}">{risk.get('name')}</strong>
                    <span class="badge" style="background: {sev_color}">{risk.get('severity')}</span>
                </div>
                <p class="mb-2">{risk.get('description')}</p>
                <div class="metrics-row bg-gray-50 p-2 rounded flex-row justify-around mb-2">
                    <div><span class="label">Likelihood</span> <strong>{risk.get('likelihood')}%</strong></div>
                    <div><span class="label">Impact</span> <strong>{risk.get('impact')}%</strong></div>
                </div>
                <div class="text-sm">
                    <strong>🛡️ Mitigation:</strong> {risk.get('mitigation')}
                    <br><span class="text-muted italic">Contingency: {risk.get('contingencyPlan')}</span>
                </div>
            </div>
            """)

    # Mitigation Plan
    if mitigation:
        html.append('<h3 class="section-title">Mitigation Strategy</h3>')
        for item in mitigation:
            html.append(f"""
            <div class="card mb-3 no-break border-l-thick border-red">
                <div class="flex-row justify-between">
                    <strong>{item.get('area')}</strong>
                    <div>
                        <span class="badge bg-red">Priority {item.get('priority')}</span>
                        <span class="text-sm text-muted ml-2">{item.get('timeline')}</span>
                    </div>
                </div>
                <div class="mt-2 bg-gray-50 p-2 rounded text-sm">
                    <strong>Rationale:</strong> {item.get('rationale')}
                </div>
                <ul class="compact-list mt-2">
                    {"".join(f"<li>{a}</li>" for a in item.get('actions', []))}
                </ul>
            </div>
            """)

    return "\n".join(html)


def build_strategic_growth_html(sg):
    if not isinstance(sg, dict) or not sg:
        return '<div class="empty-state">Growth data not available.</div>'

    title = sg.get("title", "Strategic Growth")
    exec_summary = sg.get("executiveSummary", "")
    vision = sg.get("visionAndIntent", {})
    swot = sg.get("swotAnalysis", {})
    roadmap = sg.get("trlProgressionRoadmap", {})
    phases = roadmap.get("phases", [])
    growth_strat = sg.get("growthStrategy", {})

    html = []

    # Header
    html.append(f"""
    <div class="page-break"></div>
    <div class="section-header border-green">
        <h2 class="text-green">03. Strategic Growth</h2>
        <div class="sub-title">{title}</div>
    </div>
    """)

    # Exec Summary & Vision
    html.append(f"""
    <div class="card bg-green-light mb-4">
        <h4 class="text-green uppercase">Executive Summary</h4>
        <p>{exec_summary}</p>
    </div>

    <div class="grid-3 mb-4">
        <div class="card col-span-2">
            <h4 class="text-green uppercase">Vision</h4>
            <p>{vision.get('vision')}</p>
            <h4 class="text-green uppercase mt-2">Mission</h4>
            <p>{vision.get('mission')}</p>
        </div>
        <div class="card flex-col items-center justify-center bg-green-50">
            <h5 class="uppercase text-muted">Current Status</h5>
            <div class="text-4xl font-bold text-green my-2">TRL {vision.get('currentTRL')}</div>
            <span class="badge bg-green">{vision.get('currentPhase')}</span>
        </div>
    </div>
    """)

    # SWOT (The Modern Grid)
    def render_swot(items):
        if not items: return "-"
        return "".join(f"<div class='mb-1'>• <strong>{i.get('name') or i.get('opportunity') or i.get('threat')}</strong>: {i.get('description')}</div>" for i in items)

    html.append(f"""
    <h3 class="section-title">SWOT Analysis</h3>
    <div class="swot-grid mb-4">
        <div class="swot-box bg-green-50 border-green">
            <h5 class="text-green">Strengths</h5>
            {render_swot(swot.get('strengths', []))}
        </div>
        <div class="swot-box bg-red-50 border-red">
            <h5 class="text-red">Weaknesses</h5>
            {render_swot(swot.get('weaknesses', []))}
        </div>
        <div class="swot-box bg-blue-50 border-blue">
            <h5 class="text-blue">Opportunities</h5>
            {render_swot(swot.get('opportunities', []))}
        </div>
        <div class="swot-box bg-amber-50 border-amber">
            <h5 class="text-amber">Threats</h5>
            {render_swot(swot.get('threats', []))}
        </div>
    </div>
    """)

    # Roadmap
    html.append('<h3 class="section-title">TRL Progression Roadmap</h3>')
    for phase in phases:
        html.append(f"""
        <div class="timeline-card no-break">
            <div class="timeline-header">
                <strong>{phase.get('phaseName')}</strong>
                <span class="badge bg-green">{phase.get('status')}</span>
            </div>
            <p class="mb-2"><strong>Objective:</strong> {phase.get('objectives')}</p>
            <div class="text-sm bg-gray-50 p-2 rounded">
                <strong>Key Activities:</strong>
                <ul class="compact-list">
                    {"".join(f"<li>{a.get('activity')} ({a.get('timeline')})</li>" for a in phase.get('keyActivities', []))}
                </ul>
            </div>
        </div>
        """)

    # Growth Horizons
    short = growth_strat.get("shortTerm", {})
    medium = growth_strat.get("mediumTerm", {})
    long_t = growth_strat.get("longTerm", {})
    
    html.append(f"""
    <h3 class="section-title">Growth Horizons</h3>
    <div class="grid-3 mb-4">
        <div class="card h-full">
            <h5 class="text-green uppercase">Short Term</h5>
            <div class="text-xs text-muted mb-2">0-6 Months</div>
            <p class="text-sm">{short.get('focus')}</p>
        </div>
        <div class="card h-full">
            <h5 class="text-green uppercase">Medium Term</h5>
            <div class="text-xs text-muted mb-2">6-18 Months</div>
            <p class="text-sm">{medium.get('focus')}</p>
        </div>
        <div class="card h-full">
            <h5 class="text-green uppercase">Long Term</h5>
            <div class="text-xs text-muted mb-2">18+ Months</div>
            <p class="text-sm">{long_t.get('focus')}</p>
        </div>
    </div>
    """)

    return "\n".join(html)


def build_full_html(idea_title, overall_score, bc, ra, sg):
    return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<title>{idea_title}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
<style>
    /* --- Modern CSS Reset & Variables --- */
    :root {{
        --blue: #2563eb;
        --blue-light: #eff6ff;
        --red: #dc2626;
        --red-light: #fef2f2;
        --green: #16a34a;
        --green-light: #f0fdf4;
        --amber: #d97706;
        --gray-50: #f9fafb;
        --gray-100: #f3f4f6;
        --text-main: #1f2937;
        --text-muted: #6b7280;
    }}
    
    body {{
        font-family: 'Inter', sans-serif;
        color: var(--text-main);
        line-height: 1.5;
        font-size: 14px;
        margin: 0;
        padding: 0;
        background: #fff;
    }}

    /* --- Utilities --- */
    .uppercase {{ text-transform: uppercase; letter-spacing: 0.05em; }}
    .text-blue {{ color: var(--blue); }}
    .text-red {{ color: var(--red); }}
    .text-green {{ color: var(--green); }}
    .text-amber {{ color: var(--amber); }}
    .text-muted {{ color: var(--text-muted); }}
    .bg-blue-light {{ background: var(--blue-light); }}
    .bg-red-light {{ background: var(--red-light); }}
    .bg-green-light {{ background: var(--green-light); }}
    .bg-gray-50 {{ background: var(--gray-50); }}
    
    .font-bold {{ font-weight: 700; }}
    .text-xl {{ font-size: 1.25rem; }}
    .text-2xl {{ font-size: 1.5rem; }}
    .text-4xl {{ font-size: 2.25rem; }}
    .text-lg {{ font-size: 1.125rem; }}
    .text-sm {{ font-size: 0.875rem; }}
    .text-xs {{ font-size: 0.75rem; }}

    .mb-1 {{ margin-bottom: 0.25rem; }}
    .mb-2 {{ margin-bottom: 0.5rem; }}
    .mb-3 {{ margin-bottom: 0.75rem; }}
    .mb-4 {{ margin-bottom: 1rem; }}
    .mt-2 {{ margin-top: 0.5rem; }}
    .mt-3 {{ margin-top: 0.75rem; }}
    .ml-2 {{ margin-left: 0.5rem; }}
    .mr-4 {{ margin-right: 1rem; }}
    .p-2 {{ padding: 0.5rem; }}
    .pt-3 {{ padding-top: 0.75rem; }}

    /* --- Layouts (Grid/Flex) --- */
    .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }}
    .grid-3 {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1rem; }}
    .col-span-2 {{ grid-column: span 2; }}
    
    .flex-row {{ display: flex; flex-direction: row; }}
    .flex-col {{ display: flex; flex-direction: column; }}
    .justify-between {{ justify-content: space-between; }}
    .justify-around {{ justify-content: space-around; }}
    .items-center {{ align-items: center; }}
    .justify-center {{ justify-content: center; }}
    .h-full {{ height: 100%; }}

    /* --- Components --- */
    
    /* Header */
    .report-header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 2px solid #e5e7eb;
        padding-bottom: 20px;
        margin-bottom: 30px;
    }}
    .report-title h1 {{ font-size: 2rem; font-weight: 800; margin: 0; color: #111; }}
    .report-meta {{ font-size: 0.9rem; color: var(--text-muted); margin-top: 5px; }}

    /* Score Circle (Conic Gradient) */
    .score-circle {{
        width: 100px;
        height: 100px;
        border-radius: 50%;
        background: conic-gradient(var(--blue) {overall_score}%, #e5e7eb 0);
        display: flex;
        align-items: center;
        justify-content: center;
    }}
    .score-inner {{
        width: 85px;
        height: 85px;
        background: white;
        border-radius: 50%;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
    }}
    .score-num {{ font-size: 1.8rem; font-weight: 800; line-height: 1; }}
    .score-label {{ font-size: 0.7rem; text-transform: uppercase; color: var(--text-muted); font-weight: 700; }}

    /* Section Headers */
    .section-header {{ margin-bottom: 1.5rem; padding-left: 1rem; }}
    .section-header h2 {{ font-size: 1.5rem; margin: 0; font-weight: 800; }}
    .sub-title {{ font-size: 1rem; color: var(--text-muted); }}
    .border-blue {{ border-left: 5px solid var(--blue); }}
    .border-red {{ border-left: 5px solid var(--red); }}
    .border-green {{ border-left: 5px solid var(--green); }}

    /* Titles */
    .section-title {{
        font-size: 1.1rem;
        font-weight: 700;
        margin: 1.5rem 0 1rem 0;
        padding-bottom: 0.5rem;
        border-bottom: 1px solid #e5e7eb;
        color: #374151;
    }}
    
    /* Cards */
    .card {{
        background: white;
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        padding: 1.25rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }}
    .shadow-hover {{ box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); }}
    
    h4 {{ margin: 0 0 0.5rem 0; font-size: 0.9rem; font-weight: 700; }}
    h5 {{ margin: 0 0 0.5rem 0; font-size: 0.75rem; font-weight: 700; letter-spacing: 0.05em; }}

    /* Badges & Chips */
    .badge {{
        display: inline-block;
        padding: 0.25rem 0.75rem;
        border-radius: 9999px;
        font-size: 0.75rem;
        font-weight: 600;
        color: white;
        background: var(--text-muted);
    }}
    .bg-red {{ background: var(--red); }}
    .bg-green {{ background: var(--green); }}

    .feature-chips ul {{ list-style: none; padding: 0; display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.5rem; }}
    .feature-chips li {{ background: var(--gray-100); padding: 0.25rem 0.75rem; border-radius: 9999px; font-size: 0.8rem; border: 1px solid #e5e7eb; }}

    /* Specific Elements */
    .alert-box {{ background: var(--blue-light); padding: 10px; border-radius: 6px; font-size: 0.9rem; }}
    .border-t {{ border-top: 1px solid #e5e7eb; }}
    .border-l {{ border-left: 1px solid #e5e7eb; }}
    .border-l-thick {{ border-left-width: 4px; border-left-style: solid; }}
    .rounded {{ border-radius: 6px; }}
    .compact-list {{ margin: 0; padding-left: 1.2rem; }}
    .compact-list li {{ margin-bottom: 0.2rem; }}

    /* Comparison Table (Grid) */
    .comparison-grid {{ display: grid; grid-template-columns: 1fr 1fr 1fr; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; }}
    .comp-col {{ padding: 1rem; border-right: 1px solid #e5e7eb; }}
    .comp-col:last-child {{ border-right: none; }}
    .comp-col.highlight {{ background: var(--blue-light); }}
    .comp-header {{ font-weight: 700; margin-bottom: 0.5rem; font-size: 0.9rem; color: var(--text-muted); text-transform: uppercase; }}
    .comp-body {{ font-size: 0.9rem; }}

    /* SWOT Grid */
    .swot-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }}
    .swot-box {{ padding: 1rem; border-radius: 8px; border-top-width: 4px; border-top-style: solid; }}
    .border-amber {{ border-color: var(--amber); }}
    .text-amber {{ color: var(--amber); }}
    .bg-amber-50 {{ background: #fffbeb; }}
    .bg-blue-50 {{ background: #eff6ff; }}
    .bg-red-50 {{ background: #fef2f2; }}
    .bg-green-50 {{ background: #f0fdf4; }}

    /* Timeline */
    .timeline-card {{ 
        border-left: 2px solid #e5e7eb; 
        padding-left: 1.5rem; 
        position: relative; 
        margin-bottom: 1.5rem; 
    }}
    .timeline-card::before {{
        content: '';
        position: absolute;
        left: -6px;
        top: 0;
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: var(--green);
        border: 2px solid white;
    }}
    .timeline-header {{ display: flex; justify-content: space-between; margin-bottom: 0.5rem; }}

    /* Label Pill */
    .label {{
        text-transform: uppercase;
        font-size: 0.65rem;
        font-weight: 700;
        color: var(--text-muted);
        letter-spacing: 0.05em;
    }}

    /* Print Controls */
    .page-break {{ page-break-before: always; }}
    .no-break {{ page-break-inside: avoid; }}

</style>
</head>
<body>

    <div class="report-header">
        <div class="report-title">
            <div class="uppercase text-muted font-bold text-xs mb-1">Pragati Innovation Report</div>
            <h1>{idea_title}</h1>
            <div class="report-meta">Generated: {datetime.now().strftime('%B %d, %Y')}</div>
        </div>
        <div class="score-circle">
            <div class="score-inner">
                <span class="score-num">{int(overall_score)}</span>
                <span class="score-label">Score</span>
            </div>
        </div>
    </div>

    {build_business_case_html(bc)}
    {build_risk_assessment_html(ra)}
    {build_strategic_growth_html(sg)}

</body>
</html>
"""

# ---------------------------- Routes ----------------------------

@reports_pdf_bp.route("/<report_id>/infographic-pdf", methods=["GET"])
@requires_auth()
def download_infographic_pdf(report_id):
    try:
        # 1. Validation & Data Fetching
        oid = parse_oid(report_id)
        if not oid: return jsonify({"error": "Invalid report ID"}), 400

        report = results_coll.find_one({"_id": oid})
        if not report: return jsonify({"error": "Report not found"}), 404

        user_id = getattr(request, "user_id", None)
        user_role = getattr(request, "user_role", None)
        if not ids_match(user_id, report.get("userId")) and user_role not in ["ttc_coordinator", "college_admin", "super_admin"]:
            return jsonify({"error": "Unauthorized"}), 403

        # 2. Extract Data
        idea_oid = parse_oid(report.get("ideaId"))
        idea = ideas_coll.find_one({"_id": idea_oid}) if idea_oid else None
        idea_title = idea.get("title", "Innovation Report") if idea else "Innovation Report"
        overall_score = report.get("overallScore", 0)

        bc_json = report.get("businessCaseJson", {}) or {}
        ra_json = report.get("riskAssessmentJson", {}) or {}
        sg_json = report.get("strategicGrowthViabilityJson", {}) or {}

        # ---------------------------------------------------------
        # RATE LIMITING CHECK (Max 10 distinct ideas per college/month)
        # ---------------------------------------------------------
        # 1. Resolve College ID
        college_id = idea.get("collegeId")
        if not college_id:
            # Fallback: Try to find via innovator -> TTC
            innovator_id = idea.get("innovatorId")
            innovator = users_coll.find_one({"_id": parse_oid(innovator_id)})
            if innovator:
                ttc_id = innovator.get("ttcCoordinatorId")
                if ttc_id:
                    ttc = users_coll.find_one({"_id": parse_oid(ttc_id)})
                    if ttc:
                        college_id = ttc.get("collegeId")
        
        # 2. Check Limit if college identified
        if college_id and user_role != "super_admin": # Super admin bypass
            college_id_str = str(college_id)
            now_utc = datetime.now(timezone.utc)
            start_of_month = datetime(now_utc.year, now_utc.month, 1, tzinfo=timezone.utc)
            
            # Count distinct ideas reported this month for this college
            # (Note: generated_reports_coll stores 'ideaId' as string or ObjectId - we handle both usually, 
            # but ideally we store consistent formats. Here filtering by string representation for safety)
            
            pipeline = [
                {
                    "$match": {
                        "collegeId": college_id_str,
                        "type": "PDF",
                        "createdAt": {"$gte": start_of_month}
                    }
                },
                {
                    "$group": {
                        "_id": "$ideaId"
                    }
                },
                {
                    "$count": "distinct_ideas"
                }
            ]
            
            count_res = list(generated_reports_coll.aggregate(pipeline))
            current_count = count_res[0]["distinct_ideas"] if count_res else 0
            
            # Check if THIS idea is already generated (idempotency)
            is_new_report = not generated_reports_coll.find_one({
                "collegeId": college_id_str,
                "ideaId": str(idea_oid),
                "type": "PDF",
                "createdAt": {"$gte": start_of_month}
            })
            
            if is_new_report and current_count >= 10:
                logger.warning(f"⛔ Rate limit exceeded for College {college_id_str}: {current_count}/10")
                return jsonify({
                    "error": "Monthly report limit reached",
                    "message": "Your college has reached the limit of 10 reports per month. Please contact support."
                }), 429

        # 3. Build HTML (Now with Modern CSS)
        html_content = build_full_html(idea_title, overall_score, bc_json, ra_json, sg_json)

        # 4. Generate PDF with Playwright
        if not PLAYWRIGHT_AVAILABLE:
            return jsonify({"error": "Playwright is not installed on the server."}), 500

        with sync_playwright() as p:
            # Launch Chromium (Headless)
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            # Load HTML content
            # wait_until="networkidle" ensures fonts/assets are loaded
            page.set_content(html_content, wait_until="networkidle")
            
            # Create PDF
            pdf_bytes = page.pdf(
                format="A4",
                print_background=True, # Essential for colors/shadows
                margin={
                    "top": "20mm",
                    "right": "20mm",
                    "bottom": "20mm",
                    "left": "20mm"
                },
                display_header_footer=True,
                # CSS in footer template must be inline or standard HTML
                footer_template="""
                    <div style="font-size: 10px; color: #9ca3af; font-family: sans-serif; width: 100%; text-align: center; border-top: 1px solid #e5e7eb; padding-top: 10px; margin: 0 20mm;">
                        <span>Pragati Innovation Platform &nbsp;|&nbsp; Confidential Report</span>
                        <span style="float: right;">Page <span class="pageNumber"></span> of <span class="totalPages"></span></span>
                    </div>
                """,
                header_template="<div></div>" # Empty header to avoid default
            )
            
            browser.close()

        # ---------------------------------------------------------
        # LOG USAGE (After successful generation)
        # ---------------------------------------------------------
        if college_id: # Only log if associated with a college
            try:
                generated_reports_coll.insert_one({
                    "userId": str(user_id) if user_id else None,
                    "collegeId": str(college_id),
                    "ideaId": str(idea_oid),
                    "reportName": f"Infographic - {idea_title}",
                    "type": "PDF",
                    "status": "Generated",
                    "createdAt": datetime.now(timezone.utc)
                })
                logger.info(f"✅ Usage logged for College {college_id} (Idea: {idea_oid})")
            except Exception as e:
                logger.error(f"⚠️ Failed to log report usage: {e}")

        # 5. Send File
        filename = f"pragati_report_{datetime.now().strftime('%Y%m%d')}.pdf"
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )

    except Exception as e:
        logger.error(f"Error generating PDF: {e}")
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

@reports_pdf_bp.route("/<report_id>/infographic-preview", methods=["GET"])
@requires_auth()
def preview_infographic(report_id):
    """HTML preview for debugging in browser."""
    try:
        oid = parse_oid(report_id)
        report = results_coll.find_one({"_id": oid})
        
        idea_oid = parse_oid(report.get("ideaId"))
        idea = ideas_coll.find_one({"_id": idea_oid})
        idea_title = idea.get("title", "Innovation Report")
        overall_score = report.get("overallScore", 0)

        bc = report.get("businessCaseJson", {})
        ra = report.get("riskAssessmentJson", {})
        sg = report.get("strategicGrowthViabilityJson", {})

        html = build_full_html(idea_title, overall_score, bc, ra, sg)
        return html, 200, {"Content-Type": "text/html; charset=utf-8"}
    except Exception as e:
        logger.error(f"Preview error: {e}")
        return jsonify({"error": "Error"}), 500