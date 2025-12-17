from flask import Blueprint, request, jsonify, current_app
from bson import ObjectId
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from app.database.mongo import users_coll, ideas_coll, results_coll
from app.middleware.auth import requires_auth, requires_role
from app.utils.validators import clean_doc, normalize_user_id

import logging

logger = logging.getLogger(__name__)

# ✅ CREATE BLUEPRINT with URL prefix
dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/api/dashboard')


# ✅ Helper function to find user
def find_user(user_id):
    """Find user by ID (supports both ObjectId and string)"""
    if not user_id:
        return None
    
    try:
        query = normalize_user_id(user_id)
        query["isDeleted"] = {"$ne": True}
        return users_coll.find_one(query)
    except:
        return None


# ✅ USE @requires_role decorator instead of authenticate_request()
@dashboard_bp.route("/principal/stats", methods=["GET"])
@requires_role(['college_admin', 'principal'])  # ✅ Use decorator!
def get_principal_stats():
    """
    Dashboard statistics for college principal/admin.
    """
    print("=" * 80)
    print("📊 PRINCIPAL STATS REQUESTED")
    print("=" * 80)
    
    try:
        # ✅ Get user info from request object (set by middleware)
        caller_id = request.user_id
        caller_role = request.user_role
        
        logger.info(f"📊 Principal stats requested by {caller_id}")
        
        # Convert to ObjectId if string
        if isinstance(caller_id, str):
            try:
                caller_id = ObjectId(caller_id)
            except:
                pass
        
        # College ID = principal's _id
        college_id = caller_id
        college_id_str = str(college_id)
        
        print(f"👤 College Admin ID: {college_id_str}")
        print(f"👤 Role: {caller_role}")
        
        # =========================================================================
        # 1. CREDITS TRACKING
        # =========================================================================
        principal = users_coll.find_one({"_id": college_id})
        if not principal:
            return jsonify({"error": "College admin not found"}), 404
        
        credits_total = principal.get("creditQuota", 0)
        credits_used = principal.get("creditsUsed", 0)
        credits_available = max(0, credits_total - credits_used)
        
        print(f"💰 Credits: Total={credits_total}, Used={credits_used}, Available={credits_available}")
        
        # =========================================================================
        # 2. TTC COORDINATORS
        # =========================================================================
        ttc_count = users_coll.count_documents({
            "collegeId": college_id_str,
            "role": "ttc_coordinator",
            "isDeleted": {"$ne": True}
        })
        
        ttc_limit = principal.get("ttcCoordinatorLimit", 10)
        
        # Get TTC IDs for filtering innovators
        ttc_ids = users_coll.distinct("_id", {
            "collegeId": college_id_str,
            "role": "ttc_coordinator",
            "isDeleted": {"$ne": True}
        })
        
        ttc_ids_str = [str(tid) for tid in ttc_ids]
        
        print(f"👥 TTC Coordinators: {ttc_count} (limit: {ttc_limit})")
        print(f"📋 TTC IDs: {ttc_ids_str}")
        
        # =========================================================================
        # 3. INNOVATORS
        # =========================================================================
        innovator_count = users_coll.count_documents({
            "ttcCoordinatorId": {"$in": ttc_ids_str},
            "role": {"$in": ["innovator", "individual_innovator"]},
            "isDeleted": {"$ne": True}
        })
        
        # Get innovator IDs for filtering ideas
        innovator_ids = users_coll.distinct("_id", {
            "ttcCoordinatorId": {"$in": ttc_ids_str},
            "role": {"$in": ["innovator", "individual_innovator"]},
            "isDeleted": {"$ne": True}
        })
        
        print(f"👨‍🎓 Innovators: {innovator_count}")
        
        # =========================================================================
        # 4. IDEAS
        # =========================================================================
        ideas = list(ideas_coll.find({
            "innovatorId": {"$in": innovator_ids},
            "isDeleted": {"$ne": True}
        }))
        
        idea_count = len(ideas)
        print(f"💡 Ideas: {idea_count}")
        
        # =========================================================================
        # 5. IDEA STATUS DISTRIBUTION
        # =========================================================================
        status_counts = defaultdict(int)
        for idea in ideas:
            result = results_coll.find_one({"ideaId": str(idea["_id"])})
            if result:
                outcome = result.get("validationOutcome", "Pending")
            else:
                outcome = idea.get("status", "Pending")
            status_counts[outcome] += 1
        
        status_distribution = [
            {"name": "Approved", "value": status_counts.get("Approved", 0)},
            {"name": "Moderate", "value": status_counts.get("Moderate", 0)},
            {"name": "Rejected", "value": status_counts.get("Rejected", 0)},
            {"name": "Pending", "value": status_counts.get("Pending", 0)},
        ]
        
        print(f"📊 Status Distribution: {status_distribution}")
        
        # =========================================================================
        # 6. SUBMISSION TREND (Last 6 months)
        # =========================================================================
        now = datetime.now(timezone.utc)
        six_months_ago = now - timedelta(days=180)
        submission_trend = defaultdict(int)
        
        print(f"📅 Analyzing submission trend from {six_months_ago.strftime('%Y-%m-%d')}")
        
        for idea in ideas:
            submitted_at = idea.get("submittedAt")
            if submitted_at:
                # Ensure timezone-aware comparison
                if submitted_at.tzinfo is None:
                    # Assume UTC if no timezone
                    submitted_at = submitted_at.replace(tzinfo=timezone.utc)
                
                if submitted_at >= six_months_ago:
                    month_key = submitted_at.strftime("%b %Y")
                    submission_trend[month_key] += 1
                    print(f"   ✓ Idea submitted: {submitted_at.strftime('%Y-%m-%d')} -> {month_key}")
        
        # Generate last 6 months in chronological order
        last_6_months = []
        for i in range(5, -1, -1):
            month = now - timedelta(days=30 * i)
            month_key = month.strftime("%b %Y")
            count = submission_trend.get(month_key, 0)
            last_6_months.append({"name": month_key, "ideas": count})
            print(f"   {month_key}: {count} ideas")
        
        print(f"📅 Submission Trend: {last_6_months}")
        
        
        # =========================================================================
        # 7. TOP INNOVATORS
        # =========================================================================
        innovator_scores = defaultdict(lambda: {"total": 0, "count": 0, "name": ""})
        
        for idea in ideas:
            result = results_coll.find_one({"ideaId": str(idea["_id"])})
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
        
        print(f"🏆 Top Innovators: {[i['name'] for i in top_innovators]}")
        
        # =========================================================================
        # 8. CLUSTER PERFORMANCE
        # =========================================================================
        cluster_scores = defaultdict(list)
        
        for idea in ideas:
            result = results_coll.find_one({"ideaId": str(idea["_id"])})
            if result:
                cluster_scores_obj = result.get("clusterScores", {})
                for cluster_name, score in cluster_scores_obj.items():
                    if score is not None:
                        cluster_scores[cluster_name].append(score)
        
        # Calculate averages
        cluster_performance = []
        for cluster_name, scores in cluster_scores.items():
            if scores:
                avg_score = round(sum(scores) / len(scores), 2)
                cluster_performance.append({
                    "cluster": cluster_name,
                    "score": avg_score
                })
        
        print(f"🕸️  Cluster Performance: {cluster_performance}")
        
        # =========================================================================
        # 9. STATISTICS
        # =========================================================================
        validated_ideas = [i for i in ideas if results_coll.find_one({"ideaId": str(i["_id"])})]
        
        avg_score = 0
        if validated_ideas:
            total_score = 0
            for idea in validated_ideas:
                result = results_coll.find_one({"ideaId": str(idea["_id"])})
                if result:
                    total_score += result.get("overallScore", 0)
            avg_score = round(total_score / len(validated_ideas), 2) if validated_ideas else 0
        
        statistics = {
            "ttcCount": ttc_count,
            "innovatorCount": innovator_count,
            "ideaCount": idea_count,
            "validatedIdeas": len(validated_ideas),
            "averageScore": avg_score
        }
        
        print("=" * 80)
        print("✅ DASHBOARD DATA COMPILED SUCCESSFULLY")
        print("=" * 80)
        
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
                    "total": ttc_limit,
                    "available": ttc_limit - ttc_count
                },
                "statistics": statistics,
                "statusDistribution": status_distribution,
                "submissionTrend": last_6_months,
                "topInnovators": top_innovators,
                "clusterPerformance": cluster_performance
            }
        }), 200
        
    except Exception as e:
        print("=" * 80)
        print(f"❌ ERROR in get_principal_stats: {type(e).__name__}")
        print(f"❌ Message: {str(e)}")
        print("=" * 80)
        logger.error(f"Failed to fetch principal stats: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
