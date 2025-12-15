"""
Dashboard API - Statistics for all roles
"""

from flask import Blueprint, request, jsonify
from app.database.mongo import users_coll, ideas_coll, results_coll
from app.utils.id_helpers import find_user
from datetime import datetime, timezone, timedelta
from bson import ObjectId
from collections import defaultdict
import logging

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/api/dashboard")
logger = logging.getLogger(__name__)


def authenticate_request():
    """Helper function to authenticate"""
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return None, None, {"error": "Missing authorization"}, 401
    
    try:
        from app.services.auth_service import AuthService
        from flask import current_app
        
        token = auth_header.replace('Bearer ', '').strip()
        auth_service = AuthService(current_app.config['JWT_SECRET'])
        payload = auth_service.decode_token(token)
        
        caller_id = payload.get('uid')
        caller_role = payload.get('role')
        
        if isinstance(caller_id, str):
            caller_id = ObjectId(caller_id)
        
        return caller_id, caller_role, None, None
    except Exception as e:
        return None, None, {"error": "Authentication failed"}, 401


@dashboard_bp.route("/principal/stats", methods=["GET"])
def get_principal_stats():
    """
    Dashboard statistics for college principal/admin.
    """
    try:
        # Authenticate
        caller_id, caller_role, error, status = authenticate_request()
        if error:
            return jsonify(error), status
        
        # Check role
        if caller_role not in ["college_admin", "principal"]:
            return jsonify({"error": "Access denied"}), 403
        
        logger.info(f"📊 Principal stats requested by {caller_id}")
        
        # College ID = principal's _id
        college_id = caller_id
        
        # =========================================================================
        # 1. CREDITS TRACKING
        # =========================================================================
        principal = users_coll.find_one({"_id": college_id})
        credits_total = principal.get("creditQuota", 0)
        credits_used = principal.get("creditsUsed", 0)
        credits_available = max(0, credits_total - credits_used)
        
        # =========================================================================
        # 2. TTC COORDINATORS
        # =========================================================================
        ttc_count = users_coll.count_documents({
            "collegeId": college_id,
            "role": "ttc_coordinator",
            "isDeleted": {"$ne": True}
        })
        
        ttc_limit = principal.get("ttcCoordinatorLimit", 10)
        
        # Get TTC IDs for filtering innovators
        ttc_ids = users_coll.distinct("_id", {
            "collegeId": college_id,
            "role": "ttc_coordinator",
            "isDeleted": {"$ne": True}
        })
        
        # =========================================================================
        # 3. INNOVATORS
        # =========================================================================
        innovator_count = users_coll.count_documents({
            "ttcCoordinatorId": {"$in": ttc_ids},
            "role": "innovator",
            "isDeleted": {"$ne": True}
        })
        
        # Get innovator IDs for filtering ideas
        innovator_ids = users_coll.distinct("_id", {
            "ttcCoordinatorId": {"$in": ttc_ids},
            "role": "innovator",
            "isDeleted": {"$ne": True}
        })
        
        # =========================================================================
        # 4. IDEAS
        # =========================================================================
        ideas = list(ideas_coll.find({
            "innovatorId": {"$in": innovator_ids},
            "isDeleted": {"$ne": True}
        }))
        
        idea_count = len(ideas)
        
        # =========================================================================
        # 5. IDEA STATUS DISTRIBUTION
        # =========================================================================
        status_counts = defaultdict(int)
        
        for idea in ideas:
            result = results_coll.find_one({"ideaId": idea["_id"]})
            
            if result:
                outcome = result.get("validationOutcome", "Pending")
            else:
                outcome = idea.get("stage", "Pending")
            
            status_counts[outcome] += 1
        
        status_distribution = [
            {"name": "Approved", "value": status_counts.get("Approved", 0)},
            {"name": "Moderate", "value": status_counts.get("Moderate", 0)},
            {"name": "Rejected", "value": status_counts.get("Rejected", 0)},
            {"name": "Pending", "value": status_counts.get("Pending", 0)},
        ]
        
        # =========================================================================
        # 6. SUBMISSION TREND (Last 6 months by month)
        # =========================================================================
        six_months_ago = datetime.now(timezone.utc) - timedelta(days=180)
        
        submission_trend = defaultdict(int)
        for idea in ideas:
            submitted_at = idea.get("submittedAt")
            if submitted_at and submitted_at >= six_months_ago:
                month_key = submitted_at.strftime("%b")
                submission_trend[month_key] += 1
        
        # Sort by chronological order
        month_order = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        current_month = datetime.now().month
        
        # Get last 6 months in order
        last_6_months = []
        for i in range(5, -1, -1):
            month_idx = (current_month - i - 1) % 12
            month_name = month_order[month_idx]
            last_6_months.append({"name": month_name, "ideas": submission_trend.get(month_name, 0)})
        
        # =========================================================================
        # 7. TOP INNOVATORS (by average score)
        # =========================================================================
        innovator_scores = defaultdict(lambda: {"total": 0, "count": 0, "name": ""})
        
        for idea in ideas:
            result = results_coll.find_one({"ideaId": idea["_id"]})
            if result and result.get("overallScore"):
                innovator_id = idea.get("innovatorId")
                score = result.get("overallScore", 0)
                
                if innovator_id not in innovator_scores:
                    innovator = find_user(innovator_id)
                    innovator_scores[innovator_id]["name"] = innovator.get("name", "Unknown") if innovator else "Unknown"
                
                innovator_scores[innovator_id]["total"] += score
                innovator_scores[innovator_id]["count"] += 1
        
        # Calculate averages
        top_innovators = []
        for innovator_id, data in innovator_scores.items():
            if data["count"] > 0:
                avg_score = data["total"] / data["count"]
                top_innovators.append({
                    "name": data["name"],
                    "score": round(avg_score, 2)
                })
        
        # Sort and take top 5
        top_innovators.sort(key=lambda x: x["score"], reverse=True)
        top_innovators = top_innovators[:5]
        
        # =========================================================================
        # 8. CLUSTER PERFORMANCE (Average scores across all ideas)
        # =========================================================================
        cluster_scores = defaultdict(list)
        
        for idea in ideas:
            result = results_coll.find_one({"ideaId": idea["_id"]})
            if result and result.get("sections", {}).get("detailedEvaluation", {}).get("clusters"):
                clusters = result["sections"]["detailedEvaluation"]["clusters"]
                
                for cluster_name, cluster_data in clusters.items():
                    # Calculate average score for this cluster
                    scores = []
                    for param_data in cluster_data.values():
                        for sub_param_data in param_data.values():
                            if isinstance(sub_param_data, dict) and "assignedScore" in sub_param_data:
                                scores.append(sub_param_data["assignedScore"])
                    
                    if scores:
                        cluster_avg = sum(scores) / len(scores)
                        cluster_scores[cluster_name].append(cluster_avg)
        
        # Calculate overall cluster averages
        avg_cluster_scores = {}
        for cluster_name, scores in cluster_scores.items():
            if scores:
                avg_cluster_scores[cluster_name] = round(sum(scores) / len(scores), 2)
        
        # =========================================================================
        # RESPONSE
        # =========================================================================
        return jsonify({
            "success": True,
            "data": {
                "credits": {
                    "total": credits_total,
                    "used": credits_used,
                    "available": credits_available
                },
                "ttc": {
                    "used": ttc_count,
                    "total": ttc_limit
                },
                "statistics": {
                    "ttcCount": ttc_count,
                    "innovatorCount": innovator_count,
                    "ideaCount": idea_count
                },
                "statusDistribution": status_distribution,
                "submissionTrend": last_6_months,
                "topInnovators": top_innovators,
                "clusterPerformance": avg_cluster_scores
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Failed to fetch principal stats: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route("/my-credits", methods=["GET"])
def get_my_credits():
    """Get credit information for any user role"""
    try:
        caller_id, caller_role, error, status = authenticate_request()
        if error:
            return jsonify(error), status
        
        user = users_coll.find_one({"_id": caller_id})
        if not user:
            return jsonify({"error": "User not found"}), 404
        
        credit_quota = user.get("creditQuota", 0)
        credits_used = user.get("creditsUsed", 0)
        credits_available = max(0, credit_quota - credits_used)
        
        return jsonify({
            "success": True,
            "data": {
                "total": credit_quota,
                "used": credits_used,
                "available": credits_available,
                "percentage": round((credits_used / credit_quota * 100) if credit_quota > 0 else 0, 2)
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Failed to fetch credits: {e}")
        return jsonify({"error": str(e)}), 500
