# app/services/pdf_generator_service.py
"""
Professional PDF generation service for validation reports.
Generates infographic-rich, easy-to-understand PDFs.
"""

from jinja2 import Environment, FileSystemLoader, TemplateNotFound
import io
import os
import base64
import logging
from datetime import datetime
from xhtml2pdf import pisa
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

# Import utilities
from app.utils.data_processors import DataProcessor

logger = logging.getLogger(__name__)


class ChartGenerator:
    """Generate charts and visualizations for PDF reports."""
    
    def generate_score_gauge(self, score):
        """Generate a circular score gauge as base64 PNG."""
        try:
            fig, ax = plt.subplots(figsize=(4, 4), subplot_kw={'projection': 'polar'})
            
            # Score as percentage of circle
            theta = np.linspace(0, 2 * np.pi * (score / 100), 100)
            r = np.ones(100)
            
            # Background circle
            theta_bg = np.linspace(0, 2 * np.pi, 100)
            ax.fill_between(theta_bg, 0, 1, color='#E5E7EB', alpha=0.5)
            
            # Score arc
            color = self._score_to_color(score)
            ax.fill_between(theta, 0, r, color=color, alpha=0.8)
            
            # Center text
            ax.annotate(
                f'{score:.0f}',
                xy=(0, 0),
                fontsize=36,
                fontweight='bold',
                ha='center',
                va='center',
                color='#1F2937'
            )
            
            ax.set_ylim(0, 1)
            ax.set_yticklabels([])
            ax.set_xticklabels([])
            ax.spines['polar'].set_visible(False)
            
            plt.tight_layout()
            
            img_buffer = io.BytesIO()
            plt.savefig(img_buffer, format='png', dpi=100, bbox_inches='tight', 
                       facecolor='white', edgecolor='none')
            img_buffer.seek(0)
            plt.close(fig)
            
            return base64.b64encode(img_buffer.read()).decode('utf-8')
        
        except Exception as e:
            logger.error(f"❌ Score gauge generation error: {e}")
            return None
    
    def generate_spider_chart(self, cluster_scores):
        """Generate spider/radar chart for cluster analysis."""
        try:
            # Extract labels and values
            if isinstance(cluster_scores, dict):
                labels = []
                values = []
                for key, data in cluster_scores.items():
                    if isinstance(data, dict):
                        labels.append(data.get('name', key))
                        values.append(data.get('score', 0))
                    else:
                        labels.append(key)
                        values.append(data)
            else:
                labels = [item.get('name', '') for item in cluster_scores]
                values = [item.get('score', 0) for item in cluster_scores]
            
            if not labels or not values:
                return None
            
            num_vars = len(labels)
            angles = np.linspace(0, 2 * np.pi, num_vars, endpoint=False).tolist()
            values_plot = values + values[:1]
            angles_plot = angles + angles[:1]
            
            fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True), facecolor='white')
            
            ax.plot(angles_plot, values_plot, 'o-', linewidth=2.5, color='#3B82F6', markersize=8)
            ax.fill(angles_plot, values_plot, alpha=0.25, color='#3B82F6')
            
            ax.set_xticks(angles)
            ax.set_xticklabels(labels, fontsize=10, fontweight='bold', color='#333')
            ax.set_ylim(0, 100)
            ax.set_yticks([20, 40, 60, 80, 100])
            ax.set_yticklabels(['20', '40', '60', '80', '100'], fontsize=9, color='#999')
            ax.grid(True, linestyle='--', alpha=0.7, color='#ddd')
            ax.set_facecolor('#ffffff')
            
            fig.suptitle('Cluster Performance Analysis', fontsize=14, fontweight='bold', 
                        color='#1F2937', y=0.98)
            
            plt.tight_layout()
            
            img_buffer = io.BytesIO()
            plt.savefig(img_buffer, format='png', dpi=120, bbox_inches='tight',
                       facecolor='white', edgecolor='none')
            img_buffer.seek(0)
            plt.close(fig)
            
            return base64.b64encode(img_buffer.read()).decode('utf-8')
        
        except Exception as e:
            logger.error(f"❌ Spider chart generation error: {e}")
            return None
    
    def generate_risk_matrix(self, critical_risks, high_risks):
        """Generate risk matrix visualization."""
        try:
            fig, ax = plt.subplots(figsize=(6, 4), facecolor='white')
            
            # Risk counts
            categories = ['Critical', 'High', 'Medium', 'Low']
            counts = [len(critical_risks), len(high_risks), 0, 0]
            colors = ['#EF4444', '#F97316', '#F59E0B', '#10B981']
            
            bars = ax.barh(categories, counts, color=colors)
            ax.set_xlabel('Number of Risks')
            ax.set_title('Risk Distribution', fontweight='bold')
            
            for bar, count in zip(bars, counts):
                if count > 0:
                    ax.text(bar.get_width() + 0.1, bar.get_y() + bar.get_height()/2,
                           str(count), va='center', fontweight='bold')
            
            plt.tight_layout()
            
            img_buffer = io.BytesIO()
            plt.savefig(img_buffer, format='png', dpi=100, bbox_inches='tight',
                       facecolor='white', edgecolor='none')
            img_buffer.seek(0)
            plt.close(fig)
            
            return base64.b64encode(img_buffer.read()).decode('utf-8')
        
        except Exception as e:
            logger.error(f"❌ Risk matrix generation error: {e}")
            return None
    
    def generate_timeline(self, roadmap):
        """Generate timeline visualization."""
        try:
            if not roadmap:
                return None
            
            fig, ax = plt.subplots(figsize=(10, 3), facecolor='white')
            
            phases = roadmap[:5]  # Limit to 5 phases
            for i, phase in enumerate(phases):
                ax.plot(i, 0, 'o', markersize=20, color='#3B82F6')
                ax.annotate(phase.get('phase', f'Phase {i+1}'), 
                           xy=(i, 0), xytext=(i, 0.5),
                           ha='center', fontsize=10, fontweight='bold')
            
            ax.plot(range(len(phases)), [0] * len(phases), '-', color='#3B82F6', linewidth=2)
            ax.set_ylim(-1, 1.5)
            ax.set_xlim(-0.5, len(phases) - 0.5)
            ax.axis('off')
            ax.set_title('Growth Roadmap', fontweight='bold', pad=20)
            
            plt.tight_layout()
            
            img_buffer = io.BytesIO()
            plt.savefig(img_buffer, format='png', dpi=100, bbox_inches='tight',
                       facecolor='white', edgecolor='none')
            img_buffer.seek(0)
            plt.close(fig)
            
            return base64.b64encode(img_buffer.read()).decode('utf-8')
        
        except Exception as e:
            logger.error(f"❌ Timeline generation error: {e}")
            return None
    
    def generate_score_breakdown(self, cluster_scores):
        """Generate horizontal bar chart for score breakdown."""
        try:
            if isinstance(cluster_scores, dict):
                labels = []
                values = []
                for key, data in cluster_scores.items():
                    if isinstance(data, dict):
                        labels.append(data.get('name', key))
                        values.append(data.get('score', 0))
                    else:
                        labels.append(key)
                        values.append(data)
            else:
                return None
            
            fig, ax = plt.subplots(figsize=(8, 5), facecolor='white')
            
            colors = [self._score_to_color(v) for v in values]
            y_pos = np.arange(len(labels))
            
            bars = ax.barh(y_pos, values, color=colors)
            ax.set_yticks(y_pos)
            ax.set_yticklabels(labels, fontsize=10)
            ax.set_xlim(0, 100)
            ax.set_xlabel('Score')
            ax.set_title('Performance by Category', fontweight='bold')
            
            for bar, value in zip(bars, values):
                ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height()/2,
                       f'{value:.0f}', va='center', fontsize=10, fontweight='bold')
            
            plt.tight_layout()
            
            img_buffer = io.BytesIO()
            plt.savefig(img_buffer, format='png', dpi=100, bbox_inches='tight',
                       facecolor='white', edgecolor='none')
            img_buffer.seek(0)
            plt.close(fig)
            
            return base64.b64encode(img_buffer.read()).decode('utf-8')
        
        except Exception as e:
            logger.error(f"❌ Score breakdown generation error: {e}")
            return None
    
    def _score_to_color(self, score):
        """Convert score to color."""
        if score >= 80:
            return '#10B981'  # Green
        elif score >= 60:
            return '#3B82F6'  # Blue
        elif score >= 40:
            return '#F59E0B'  # Amber
        else:
            return '#EF4444'  # Red


class PDFGeneratorService:
    """
    Professional PDF generation service for validation reports.
    Generates infographic-rich, easy-to-understand PDFs.
    """
    
    def __init__(self, app):
        self.app = app
        self.chart_gen = ChartGenerator()
        self.data_processor = DataProcessor()
        self.template_dir = os.path.join(
            os.path.dirname(__file__),
            '..',
            'templates'
        )
    
    # ========================================================================
    # MAIN ENTRY POINT
    # ========================================================================
    
    def generate_professional_pdf(self, report):
        """
        Generate complete professional PDF from report data.
        
        Returns: BytesIO object with PDF content
        """
        try:
            logger.info("🎨 Starting PDF generation...")
            
            # 1. Extract and process data
            processed_data = self._process_report_data(report)
            logger.info("✅ Data processing complete")
            
            # 2. Generate visualizations
            charts = self._generate_charts(processed_data)
            processed_data['charts'] = charts
            logger.info("✅ Charts generated")
            
            # 3. Render HTML template
            html_content = self.generate_html_content(report, processed_data)
            logger.info("✅ HTML rendered")
            
            # 4. Convert to PDF
            pdf_buffer = self._html_to_pdf(html_content)
            logger.info("✅ PDF generated successfully")
            
            return pdf_buffer
        
        except Exception as e:
            logger.exception(f"❌ PDF generation failed: {e}")
            raise
    
    # ========================================================================
    # DATA PROCESSING
    # ========================================================================
    
    def _process_report_data(self, report):
        """Extract and structure data for template."""
        try:
            processed = {
                # Cover Page
                'title': report.get('extractedIdeaName', 'Validation Report'),
                'description': report.get('shortDescription', report.get('ideaDescription', '')),
                'overall_score': report.get('overallScore', 0),
                'validation_outcome': report.get('validationOutcome', 'UNKNOWN'),
                'generated_date': datetime.now().strftime('%B %d, %Y'),
                'report_id': str(report.get('_id', '')),
                
                # Business Case
                'business_case': self._extract_business_case(report),
                
                # Risk Assessment
                'risk_assessment': self._extract_risk_assessment(report),
                
                # Strategic Growth
                'strategic_growth': self._extract_strategic_growth(report),
                
                # Cluster Scores
                'cluster_scores': self._extract_cluster_scores(report),
                
                # Action Points
                'action_points': self._extract_action_points(report),
                
                # Key Metrics
                'top_strengths': [],
                'areas_for_improvement': [],
            }
            
            # Calculate strengths and weaknesses
            processed['top_strengths'], processed['areas_for_improvement'] = \
                self.data_processor.extract_strengths_weaknesses(processed['cluster_scores'])
            
            return processed
        
        except Exception as e:
            logger.error(f"❌ Data processing error: {e}")
            raise
    
    def _extract_business_case(self, report):
        """Extract business case information."""
        bc = report.get('businessCase', {})
        return {
            'market_opportunity': bc.get('marketOpportunity', 'Not provided'),
            'target_customer': bc.get('targetCustomer', 'Not provided'),
            'revenue_model': bc.get('revenueModel', 'Not provided'),
            'competitive_advantage': bc.get('competitiveAdvantage', 'Not provided'),
            'go_to_market': bc.get('goToMarketStrategy', 'Not provided'),
            'financial': bc.get('financialProjections', {}),
        }
    
    def _extract_risk_assessment(self, report):
        """Extract risk assessment information."""
        ra = report.get('riskAssessment', {})
        risks = ra.get('risks', ra.get('identifiedRisks', []))
        
        # Categorize risks
        critical_risks = [r for r in risks if r.get('impact') == 'CRITICAL' or r.get('severity') == 'CRITICAL']
        high_risks = [r for r in risks if r.get('impact') == 'HIGH' or r.get('severity') == 'HIGH']
        medium_risks = [r for r in risks if r.get('impact') == 'MEDIUM' or r.get('severity') == 'MEDIUM']
        
        return {
            'overall_score': ra.get('overallRiskScore', 0),
            'critical_risks': critical_risks,
            'high_risks': high_risks,
            'medium_risks': medium_risks,
            'total_risks': len(risks),
        }
    
    def _extract_strategic_growth(self, report):
        """Extract strategic growth plan."""
        sg = report.get('strategicGrowth', report.get('strategicGrowthPlan', {}))
        return {
            'roadmap': sg.get('roadmap', sg.get('growthPhases', [])),
            'growth_drivers': sg.get('growthDrivers', []),
            'scale_potential': sg.get('scalePotential', 'Not provided'),
            'investment_required': sg.get('investmentRequired', 0),
        }
    
    def _extract_cluster_scores(self, report):
        """Extract cluster scores for analysis."""
        assessment = report.get('detailedViabilityAssessment', {})
        
        scores = {}
        for cluster_name, cluster_data in assessment.items():
            if isinstance(cluster_data, dict):
                score = cluster_data.get('score', cluster_data.get('avgScore', 0))
            else:
                score = cluster_data
            
            scores[cluster_name] = {
                'name': cluster_name,
                'score': score,
                'percentage': f"{score}%",
                'color': self._score_to_color(score),
                'status': self._score_to_status(score),
            }
        
        # Fallback if empty
        if not scores:
            default_score = report.get('overallScore', 50)
            scores = {
                'MarketViability': {'name': 'Market Viability', 'score': default_score},
                'TechnicalFeasibility': {'name': 'Technical Feasibility', 'score': default_score},
                'ExecutionCapability': {'name': 'Execution Capability', 'score': default_score},
                'BusinessModelStrength': {'name': 'Business Model', 'score': default_score},
                'TeamCapability': {'name': 'Team Capability', 'score': default_score},
                'EnvironmentalFactors': {'name': 'Environmental Factors', 'score': default_score},
                'RiskManagement': {'name': 'Risk Management', 'score': default_score},
            }
        
        return scores
    
    def _extract_action_points(self, report):
        """Extract action points and prioritize them."""
        actions = report.get('actionPoints', [])
        
        # Categorize by timeline
        immediate = [a for a in actions if a.get('timeline', '').lower() in ['immediate', 'asap', 'urgent']]
        short_term = [a for a in actions if a.get('timeline', '').lower() in ['short-term', '30-day', '30 days']]
        long_term = [a for a in actions if a.get('timeline', '').lower() in ['long-term', '90-day', '90 days']]
        
        return {
            'immediate': immediate[:5],
            'short_term': short_term[:5],
            'long_term': long_term[:5],
            'total': len(actions),
        }
    
    # ========================================================================
    # CHART GENERATION
    # ========================================================================
    
    def _generate_charts(self, data):
        """Generate all required visualizations."""
        charts = {}
        
        try:
            charts['score_gauge'] = self.chart_gen.generate_score_gauge(data['overall_score'])
            logger.info("✅ Score gauge generated")
        except Exception as e:
            logger.warning(f"⚠️ Score gauge generation failed: {e}")
            charts['score_gauge'] = None
        
        try:
            charts['spider_chart'] = self.chart_gen.generate_spider_chart(data['cluster_scores'])
            logger.info("✅ Spider chart generated")
        except Exception as e:
            logger.warning(f"⚠️ Spider chart generation failed: {e}")
            charts['spider_chart'] = None
        
        try:
            charts['risk_matrix'] = self.chart_gen.generate_risk_matrix(
                data['risk_assessment']['critical_risks'],
                data['risk_assessment']['high_risks']
            )
            logger.info("✅ Risk matrix generated")
        except Exception as e:
            logger.warning(f"⚠️ Risk matrix generation failed: {e}")
            charts['risk_matrix'] = None
        
        try:
            charts['timeline'] = self.chart_gen.generate_timeline(data['strategic_growth']['roadmap'])
            logger.info("✅ Timeline generated")
        except Exception as e:
            logger.warning(f"⚠️ Timeline generation failed: {e}")
            charts['timeline'] = None
        
        try:
            charts['score_breakdown'] = self.chart_gen.generate_score_breakdown(data['cluster_scores'])
            logger.info("✅ Score breakdown generated")
        except Exception as e:
            logger.warning(f"⚠️ Score breakdown generation failed: {e}")
            charts['score_breakdown'] = None
        
        return charts
    
    # ========================================================================
    # HTML RENDERING
    # ========================================================================
    
    def generate_html_content(self, report, processed_data=None):
        """Generate HTML content for PDF."""
        try:
            if not processed_data:
                processed_data = self._process_report_data(report)
                charts = self._generate_charts(processed_data)
                processed_data['charts'] = charts
            
            env = Environment(loader=FileSystemLoader(self.template_dir))
            
            # Try the templates-pdf-template.html first, then pdf_template.html
            template_names = ['templates-pdf-template.html', 'pdf_template.html']
            template = None
            
            for template_name in template_names:
                try:
                    template = env.get_template(template_name)
                    logger.info(f"✅ Using template: {template_name}")
                    break
                except TemplateNotFound:
                    continue
            
            if template is None:
                logger.warning("⚠️ No template found, using fallback")
                return self._generate_fallback_html(processed_data)
            
            html_content = template.render(
                **processed_data,
                pdf_mode=True
            )
            
            logger.info("✅ HTML template rendered")
            return html_content
        
        except TemplateNotFound:
            logger.warning("⚠️ Template not found, using fallback")
            return self._generate_fallback_html(processed_data or {})
        
        except Exception as e:
            logger.error(f"❌ HTML rendering error: {e}")
            raise
    
    def _generate_fallback_html(self, data):
        """Generate basic HTML if template is missing."""
        title = data.get('title', 'Validation Report')
        score = data.get('overall_score', 0)
        outcome = data.get('validation_outcome', 'UNKNOWN')
        
        # Spider chart
        chart_html = ""
        if data.get('charts', {}).get('spider_chart'):
            chart_html = f'<img src="data:image/png;base64,{data["charts"]["spider_chart"]}" style="max-width: 100%; margin: 20px 0;">'
        
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>{title}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; color: #333; }}
                h1 {{ color: #1F2937; border-bottom: 3px solid #3B82F6; padding-bottom: 10px; }}
                h2 {{ color: #3B82F6; margin-top: 30px; }}
                .score-box {{ 
                    background: linear-gradient(135deg, #1F2937 0%, #3B82F6 100%); 
                    padding: 30px; 
                    border-radius: 12px; 
                    text-align: center; 
                    color: white;
                    margin: 20px 0;
                }}
                .score-value {{ font-size: 64px; font-weight: bold; }}
                .score-label {{ font-size: 16px; opacity: 0.9; }}
                .outcome {{ 
                    display: inline-block; 
                    padding: 8px 16px; 
                    border-radius: 20px; 
                    background: #10B981; 
                    color: white; 
                    font-weight: bold;
                }}
                .section {{ margin-top: 30px; page-break-inside: avoid; }}
                .footer {{ 
                    margin-top: 40px; 
                    padding-top: 20px; 
                    border-top: 1px solid #ddd; 
                    font-size: 12px; 
                    color: #999; 
                    text-align: center;
                }}
            </style>
        </head>
        <body>
            <h1>{title}</h1>
            
            <div class="score-box">
                <div class="score-value">{score:.1f}</div>
                <div class="score-label">Overall Viability Score / 100</div>
            </div>
            
            <p><span class="outcome">{outcome.replace('_', ' ')}</span></p>
            
            <div class="section">
                <h2>Cluster Performance</h2>
                {chart_html}
            </div>
            
            <div class="section">
                <h2>Description</h2>
                <p>{data.get('description', 'No description provided.')}</p>
            </div>
            
            <div class="footer">
                <p>Report ID: {data.get('report_id', 'N/A')}</p>
                <p>Generated: {data.get('generated_date', datetime.now().strftime('%B %d, %Y'))}</p>
                <p><strong>Pragati Innovation Suite</strong> - Confidential & Proprietary</p>
            </div>
        </body>
        </html>
        """
    
    # ========================================================================
    # PDF CONVERSION
    # ========================================================================
    
    def _html_to_pdf(self, html_content):
        """Convert HTML to PDF using xhtml2pdf."""
        try:
            pdf_buffer = io.BytesIO()
            
            pisa_status = pisa.CreatePDF(
                html_content,
                pdf_buffer,
                encoding='UTF-8'
            )
            
            if pisa_status.err:
                raise Exception(f"PDF generation error: {pisa_status.err}")
            
            pdf_buffer.seek(0)
            return pdf_buffer
        
        except Exception as e:
            logger.error(f"❌ PDF conversion error: {e}")
            raise
    
    # ========================================================================
    # HELPER METHODS
    # ========================================================================
    
    def _score_to_color(self, score):
        """Convert score to color code."""
        if score >= 80:
            return '#10B981'  # Green
        elif score >= 60:
            return '#F59E0B'  # Amber
        elif score >= 40:
            return '#F97316'  # Orange
        else:
            return '#EF4444'  # Red
    
    def _score_to_status(self, score):
        """Convert score to status label."""
        if score >= 80:
            return 'Excellent'
        elif score >= 60:
            return 'Good'
        elif score >= 40:
            return 'Fair'
        else:
            return 'Needs Work'
