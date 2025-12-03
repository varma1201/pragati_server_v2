# app/routes/reports_pdf.py - Fixed version

from flask import Blueprint, request, jsonify, current_app, send_file
from app.middleware.auth import requires_auth
from app.database.mongo import results_coll
from datetime import datetime
from bson import ObjectId
import io
import base64
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from xhtml2pdf import pisa
import os

reports_pdf_bp = Blueprint("reports_pdf", __name__, url_prefix="/api/reports")

# =========================================================================
# HELPER: Generate Spider/Radar Chart
# =========================================================================

def generate_spider_chart(cluster_data):
    """
    Generate spider chart matching your React component logic.
    
    Args:
        cluster_data: dict like {"Cluster Name": score_value}
    
    Returns:
        base64 encoded PNG string or None
    """
    try:
        # Handle both dict and list formats
        if isinstance(cluster_data, dict):
            labels = list(cluster_data.keys())
            values = list(cluster_data.values())
        else:
            labels = [item.get('cluster', '') for item in cluster_data]
            values = [item.get('score', 0) for item in cluster_data]

        if not labels or not values:
            current_app.logger.warning("No cluster data for spider chart")
            return None

        num_vars = len(labels)

        # Compute angles for spider/radar chart
        angles = np.linspace(0, 2 * np.pi, num_vars, endpoint=False).tolist()
        values_plot = values + values[:1]  # Complete the loop
        angles_plot = angles + angles[:1]

        # Create figure with polar projection
        fig, ax = plt.subplots(
            figsize=(8, 8),
            subplot_kw=dict(polar=True),
            facecolor='white'
        )

        # Plot the data
        ax.plot(angles_plot, values_plot, 'o-', linewidth=2.5, color='#2a7f62', markersize=8)
        ax.fill(angles_plot, values_plot, alpha=0.25, color='#2a7f62')

        # Set labels
        ax.set_xticks(angles)
        ax.set_xticklabels(
            labels,
            fontsize=11,
            fontweight='bold',
            color='#333'
        )

        # Set radial limits and ticks
        ax.set_ylim(0, 100)
        ax.set_yticks([20, 40, 60, 80, 100])
        ax.set_yticklabels(['20', '40', '60', '80', '100'], fontsize=9, color='#999')

        # Grid styling
        ax.grid(True, linestyle='--', alpha=0.7, color='#ddd')
        ax.set_facecolor('#ffffff')

        # Title
        fig.suptitle(
            'Cluster Performance Analysis',
            fontsize=14,
            fontweight='bold',
            color='#1a5f47',
            y=0.98
        )

        # Tight layout
        plt.tight_layout()

        # Save to bytes
        img_buffer = io.BytesIO()
        plt.savefig(
            img_buffer,
            format='png',
            dpi=120,
            bbox_inches='tight',
            facecolor='white',
            edgecolor='none'
        )

        img_buffer.seek(0)
        plt.close(fig)

        # Encode to base64
        b64_chart = base64.b64encode(img_buffer.read()).decode('utf-8')

        current_app.logger.info(f"✅ Spider chart generated: {len(labels)} clusters")

        return b64_chart

    except Exception as e:
        current_app.logger.error(f"❌ Spider chart error: {e}")
        return None


# =========================================================================
# HELPER: Generate Fallback HTML
# =========================================================================

def _generate_fallback_html(title, score, outcome, points, chart_b64, clusters, report_id):
    """Fallback HTML if template file not found"""
    
    chart_html = f'<img src="data:image/png;base64,{chart_b64}" style="max-width: 100%; margin: 20px 0;">' if chart_b64 else ""
    
    points_html = "<ul>" + "".join([f"<li>{p}</li>" for p in points]) + "</ul>"
    
    clusters_html = "".join([
        f"<tr><td>{name}</td><td style='text-align: center;'>{score:.0f}/100</td></tr>"
        for name, score in clusters.items()
    ])

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Validation Report</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; color: #333; }}
            h1 {{ color: #1a5f47; border-bottom: 3px solid #2a7f62; padding-bottom: 10px; }}
            h2 {{ color: #2a7f62; margin-top: 30px; }}
            .score-box {{ 
                background: #f0f0f0; 
                padding: 20px; 
                border-radius: 8px; 
                text-align: center; 
                margin: 20px 0;
            }}
            .score-value {{ font-size: 48px; font-weight: bold; color: #1a5f47; }}
            .score-label {{ font-size: 14px; color: #666; }}
            table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
            th {{ background: #2a7f62; color: white; padding: 10px; text-align: left; }}
            td {{ border-bottom: 1px solid #ddd; padding: 10px; }}
            tr:hover {{ background: #f9f9f9; }}
            .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 12px; color: #999; }}
        </style>
    </head>
    <body>
        <h1>{title}</h1>
        
        <div class="score-box">
            <div class="score-value">{score:.1f}</div>
            <div class="score-label">Overall Viability Score / 100</div>
        </div>
        
        <h2>Validation Outcome</h2>
        <p><strong>{outcome}</strong></p>
        
        {chart_html}
        
        <h2>Key Action Points</h2>
        {points_html if points else "<p>No specific action points identified.</p>"}
        
        <h2>Cluster Performance</h2>
        <table>
            <thead>
                <tr>
                    <th>Cluster</th>
                    <th>Score</th>
                </tr>
            </thead>
            <tbody>
                {clusters_html}
            </tbody>
        </table>
        
        <div class="footer">
            <p>Report ID: {report_id}</p>
            <p>Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}</p>
            <p>Generated by Pragati - Confidential &amp; Proprietary</p>
        </div>
    </body>
    </html>
    """


# =========================================================================
# ROUTE: Download Report as PDF with Spider Chart ✅ FIXED
# =========================================================================

@reports_pdf_bp.route("/<report_id>/download-pdf", methods=["GET"])  # ✅ FIXED: Proper route with parameter
@requires_auth
def download_report_pdf(report_id):
    """
    Download validation report as PDF with embedded spider chart.
    
    Usage: GET /api/reports/{report_id}/download-pdf
    """
    try:
        # 1. Validate report_id
        if not report_id:
            return jsonify({"error": "report_id is required"}), 400

        current_app.logger.info(f"📥 PDF download requested: {report_id}")

        # 2. Convert to ObjectId and fetch report
        try:
            if isinstance(report_id, str):
                report_oid = ObjectId(report_id)
            else:
                report_oid = report_id
        except Exception as e:
            return jsonify({"error": "Invalid report_id format"}), 400

        report = results_coll.find_one({"_id": report_oid})

        if not report:
            current_app.logger.error(f"❌ Report not found: {report_id}")
            return jsonify({"error": "Report not found"}), 404

        current_app.logger.info(f"✅ Report found: {report.get('extractedIdeaName', 'Unknown')}")

        # 3. Extract cluster scores for spider chart
        cluster_scores = {}
        detailed_assessment = report.get('detailedViabilityAssessment', {})

        # Extract scores from nested assessment structure
        if isinstance(detailed_assessment, dict):
            for cluster_name, cluster_data in detailed_assessment.items():
                if isinstance(cluster_data, dict):
                    # Try to find score in various possible locations
                    if 'score' in cluster_data:
                        cluster_scores[cluster_name] = cluster_data['score']
                    elif 'avgScore' in cluster_data:
                        cluster_scores[cluster_name] = cluster_data['avgScore']
                    else:
                        cluster_scores[cluster_name] = report.get('overallScore', 50)
                else:
                    cluster_scores[cluster_name] = cluster_data

        # Fallback if no assessment data
        if not cluster_scores:
            cluster_scores = {
                "Core Idea": report.get('overallScore', 50),
                "Market": report.get('overallScore', 50),
                "Execution": report.get('overallScore', 50),
                "Business Model": report.get('overallScore', 50),
                "Team": report.get('overallScore', 50),
                "Environment": report.get('overallScore', 50),
                "Risk": report.get('overallScore', 50),
            }

        current_app.logger.info(f"📊 Cluster scores: {cluster_scores}")

        # 4. Generate spider chart
        spider_chart_b64 = generate_spider_chart(cluster_scores)

        # 5. Process data for template
        title = report.get('extractedIdeaName') or report.get('title', 'Validation Report')
        overall_score = report.get('overallScore', 0)
        validation_outcome = report.get('validationOutcome', 'UNKNOWN')
        action_points = report.get('actionPoints', [])

        # 6. Extract top/bottom performers
        top_performers = []
        bottom_performers = []

        if isinstance(detailed_assessment, dict):
            for cluster, params in detailed_assessment.items():
                if isinstance(params, dict):
                    for param, sub_params in params.items():
                        if isinstance(sub_params, dict):
                            for sub_param_name, data in sub_params.items():
                                if isinstance(data, dict) and 'assignedScore' in data:
                                    score = data['assignedScore']
                                    item = {'name': sub_param_name, 'score': score}
                                    if score >= 85:
                                        top_performers.append(item)
                                    elif score < 70:
                                        bottom_performers.append(item)

        top_performers = sorted(top_performers, key=lambda x: x['score'], reverse=True)[:5]
        bottom_performers = sorted(bottom_performers, key=lambda x: x['score'])[:5]

        # 7. Generate HTML from template
        from jinja2 import Environment, FileSystemLoader, TemplateNotFound

        template_dir = os.path.join(
            os.path.dirname(__file__),
            '..',
            'templates'
        )

        html_content = None

        try:
            env = Environment(loader=FileSystemLoader(template_dir))
            template = env.get_template('report_template.html')
            html_content = template.render(
                title=title,
                overall_score=round(overall_score, 1),
                validation_outcome=validation_outcome,
                action_points=action_points,
                spider_chart=f"data:image/png;base64,{spider_chart_b64}" if spider_chart_b64 else "",
                top_performers=top_performers,
                bottom_performers=bottom_performers,
                generated_date=datetime.now().strftime('%B %d, %Y at %I:%M %p'),
                report_id=str(report_oid),
                detailed_assessment=detailed_assessment,
                pdf_mode=True
            )
            current_app.logger.info("✅ Template rendered successfully")
        except TemplateNotFound:
            current_app.logger.warning("⚠️ Template not found, using fallback HTML")
            html_content = _generate_fallback_html(
                title,
                overall_score,
                validation_outcome,
                action_points,
                spider_chart_b64,
                cluster_scores,
                str(report_oid)
            )
        except Exception as template_err:
            current_app.logger.error(f"❌ Template error: {template_err}")
            html_content = _generate_fallback_html(
                title,
                overall_score,
                validation_outcome,
                action_points,
                spider_chart_b64,
                cluster_scores,
                str(report_oid)
            )

        # 8. Render HTML to PDF
        try:
            pdf_buffer = io.BytesIO()
            pisa_status = pisa.CreatePDF(html_content, pdf_buffer)

            if pisa_status.err:
                current_app.logger.error(f"❌ PDF generation error: {pisa_status.err}")
                return jsonify({"error": "PDF generation failed"}), 500

            pdf_buffer.seek(0)

            # 9. Return PDF as download ✅ FIXED: filename now defined
            filename = f"validation_report_{title.replace(' ', '_')[:30]}_{datetime.now().strftime('%Y%m%d')}.pdf"

            current_app.logger.info(f"✅ PDF generated: {filename}")

            return send_file(
                pdf_buffer,
                mimetype="application/pdf",
                as_attachment=True,
                download_name=filename
            )

        except Exception as pdf_err:
            current_app.logger.error(f"❌ PDF rendering error: {pdf_err}")
            import traceback
            traceback.print_exc()
            return jsonify({
                "error": "PDF generation failed",
                "details": str(pdf_err)
            }), 500

    except Exception as e:
        current_app.logger.exception(f"❌ PDF download error: {e}")
        return jsonify({
            "error": "Failed to generate report PDF",
            "details": str(e)
        }), 500
