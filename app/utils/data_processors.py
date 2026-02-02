# app/utils/data_processors.py
"""
Data processors for PDF generation.
Handles data extraction, formatting, and validation for reports.
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class DataProcessor:
    """Process and extract data for PDF generation."""
    
    def extract_strengths_weaknesses(self, cluster_scores):
        """Extract top strengths and areas for improvement."""
        try:
            # Sort by score
            sorted_clusters = sorted(
                cluster_scores.items(),
                key=lambda x: x[1].get('score', 0) if isinstance(x[1], dict) else x[1],
                reverse=True
            )
            
            top_strengths = []
            areas_for_improvement = []
            
            for cluster_key, cluster_data in sorted_clusters:
                if isinstance(cluster_data, dict):
                    score = cluster_data.get('score', 0)
                    name = cluster_data.get('name', cluster_key)
                else:
                    score = cluster_data
                    name = cluster_key
                
                if score >= 75:
                    top_strengths.append({
                        'name': name,
                        'score': score,
                        'description': self._get_strength_description(name, score)
                    })
                elif score < 60:
                    areas_for_improvement.append({
                        'name': name,
                        'score': score,
                        'description': self._get_improvement_description(name, score)
                    })
            
            return top_strengths[:5], areas_for_improvement[:5]
        
        except Exception as e:
            logger.error(f"❌ Extraction error: {e}")
            return [], []
    
    def _get_strength_description(self, cluster_name, score):
        """Generate description for strong clusters."""
        descriptions = {
            'MarketViability': f'Strong market demand and opportunity identified ({score}/100)',
            'TechnicalFeasibility': f'Technology stack well-suited for implementation ({score}/100)',
            'ExecutionCapability': f'Strong execution capabilities demonstrated ({score}/100)',
            'BusinessModelStrength': f'Sustainable and scalable business model ({score}/100)',
            'TeamCapability': f'Team has necessary expertise and experience ({score}/100)',
            'EnvironmentalFactors': f'External environment favorable for growth ({score}/100)',
            'RiskManagement': f'Robust risk management framework in place ({score}/100)',
        }
        
        return descriptions.get(cluster_name, f'Strong performance in {cluster_name} ({score}/100)')
    
    def _get_improvement_description(self, cluster_name, score):
        """Generate description for improvement areas."""
        descriptions = {
            'MarketViability': f'Market validation and customer research needed ({score}/100)',
            'TechnicalFeasibility': f'Technical challenges need to be addressed ({score}/100)',
            'ExecutionCapability': f'Build execution team and resources ({score}/100)',
            'BusinessModelStrength': f'Business model refinement required ({score}/100)',
            'TeamCapability': f'Key hiring and skill gaps to address ({score}/100)',
            'EnvironmentalFactors': f'Monitor external factors and adapt strategy ({score}/100)',
            'RiskManagement': f'Develop comprehensive risk mitigation plans ({score}/100)',
        }
        
        return descriptions.get(cluster_name, f'Improvement needed in {cluster_name} ({score}/100)')
    
    def format_currency(self, amount):
        """Format number as currency."""
        try:
            if isinstance(amount, str):
                amount = float(amount)
            
            if amount >= 1_000_000:
                return f"{amount/1_000_000:.1f}M"
            elif amount >= 1_000:
                return f"{amount/1_000:.1f}K"
            else:
                return f"{amount:.0f}"
        
        except Exception as e:
            logger.error(f"❌ Currency formatting error: {e}")
            return "0"
    
    def format_date(self, date_obj):
        """Format date for display."""
        try:
            if isinstance(date_obj, str):
                return date_obj
            return date_obj.strftime('%B %d, %Y')
        except Exception:
            return datetime.now().strftime('%B %d, %Y')
    
    def process_action_points(self, actions):
        """Process and categorize action points."""
        try:
            immediate = []
            short_term = []
            long_term = []
            
            for action in actions:
                timeline = action.get('timeline', '').lower()
                
                if timeline in ['immediate', 'asap', 'urgent', 'this week']:
                    immediate.append(action)
                elif timeline in ['short-term', '30-day', '30 days', 'month']:
                    short_term.append(action)
                elif timeline in ['long-term', '90-day', '90 days', 'quarter']:
                    long_term.append(action)
                else:
                    short_term.append(action)
            
            return {
                'immediate': immediate[:5],
                'short_term': short_term[:5],
                'long_term': long_term[:5],
            }
        
        except Exception as e:
            logger.error(f"❌ Action processing error: {e}")
            return {'immediate': [], 'short_term': [], 'long_term': []}
    
    def extract_risk_summary(self, risks):
        """Extract risk summary statistics."""
        try:
            critical = len([r for r in risks if r.get('impact') == 'CRITICAL'])
            high = len([r for r in risks if r.get('impact') == 'HIGH'])
            medium = len([r for r in risks if r.get('impact') == 'MEDIUM'])
            low = len([r for r in risks if r.get('impact') == 'LOW'])
            
            return {
                'total': len(risks),
                'critical': critical,
                'high': high,
                'medium': medium,
                'low': low,
                'severity': 'CRITICAL' if critical > 0 else ('HIGH' if high > 0 else 'MEDIUM'),
            }
        
        except Exception as e:
            logger.error(f"❌ Risk summary error: {e}")
            return {'total': 0, 'critical': 0, 'high': 0, 'medium': 0, 'low': 0}
    
    def validate_data(self, report):
        """Validate report data completeness."""
        validations = {
            'has_title': bool(report.get('extractedIdeaName')),
            'has_score': report.get('overallScore') is not None,
            'has_business_case': bool(report.get('businessCase')),
            'has_risks': bool(report.get('riskAssessment')),
            'has_growth_plan': bool(report.get('strategicGrowth')),
            'has_clusters': bool(report.get('detailedViabilityAssessment')),
            'has_actions': bool(report.get('actionPoints')),
        }
        
        completeness = sum(validations.values()) / len(validations) * 100
        
        return {
            'validations': validations,
            'completeness': round(completeness, 1),
            'is_complete': completeness >= 70,
        }
