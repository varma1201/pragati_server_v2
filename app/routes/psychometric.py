"""
Psychometric Blueprint for CRUD Server

Handles reading, retrieving, and managing psychometric assessment data.
All AI-heavy operations (generation, evaluation, scoring) are delegated to
the dedicated psychometric microservice.
"""

from flask import Blueprint, request, jsonify
from datetime import datetime, timezone
from bson import ObjectId
import traceback
import logging

from app.database.mongo import db, users_coll, mentor_evaluations_coll
from app.middleware.auth import requires_role, requires_auth
from app.utils.validators import clean_doc
from app.utils.validators import normalize_user_id, normalize_any_id_field, clean_doc, get_user_by_any_id
from app.utils.id_helpers import find_user, ids_match

logger = logging.getLogger(__name__)

psychometric_bp = Blueprint('psychometric', __name__, url_prefix='/api/psychometric')

# Initialize collection references
assessments_coll = db.psychometric_assessments
evaluations_coll = db.psychometric_evaluations
profiles_coll = db.user_profiles


# =========================================================================
# 1. GET PSYCHOMETRIC PROFILE
# =========================================================================

@psychometric_bp.route('/profile', methods=['GET'])
@requires_auth()
def get_psychometric_profile():
    """
    Get user's psychometric profile from latest evaluation.
    Maps stored evaluation data into frontend-friendly profile shape.
    
    Returns:
        {
            "hasProfile": bool,
            "profile": {
                "profileType": str,
                "generalAnalysis": str,
                "riskAppetite": str,
                "workStyle": str,
                "motivation": str,
                "strengths": [str],
                "weaknesses": [str],
                "domainFit": str,
                "expertiseFit": str,
                "successFactors": str
            },
            "evaluationId": str,
            "overallScore": float
        }
    """
    try:
        user_id = request.user_id
        logger.info(f"Fetching psychometric profile for user: {user_id}")

        # Get latest evaluation for this user
        eval_doc = evaluations_coll.find_one(
            {"evaluation_result.user_id": user_id},
            sort=[("evaluation_result.evaluated_at", -1)]
        )

        if not eval_doc:
            logger.info(f"No psychometric profile found for user: {user_id}")
            return jsonify({"hasProfile": False}), 200

        eval_result = eval_doc.get("evaluation_result", {})

        # Extract data
        overall_score = eval_result.get("overall_score", 0)
        fit = eval_result.get("entrepreneurial_fit", {})
        dim = eval_result.get("dimension_scores", {})
        strengths = eval_result.get("strengths", [])
        areas_dev = eval_result.get("areas_for_development", [])

        # Map to profile shape
        risk_score = dim.get("risk_tolerance", 5)
        comm_score = dim.get("communication", 5)

        # Determine risk appetite
        if risk_score >= 8:
            risk_appetite = "Very High"
        elif risk_score >= 6:
            risk_appetite = "High"
        elif risk_score >= 4:
            risk_appetite = "Moderate"
        else:
            risk_appetite = "Low"

        # Determine work style
        if comm_score >= 7:
            work_style = "People-centric & Communicative"
        else:
            work_style = "Analytical & Task-focused"

        profile = {
            "profileType": f"{fit.get('overall_fit', 'Medium')} Fit {fit.get('ideal_role', 'Entrepreneur')}",
            "generalAnalysis": eval_result.get("personality_profile", ""),
            "riskAppetite": risk_appetite,
            "workStyle": work_style,
            "motivation": fit.get("ideal_venture_type", "Building a meaningful venture"),
            "strengths": strengths[:5],  # Top 5
            "weaknesses": areas_dev[:5],  # Top 5
            "domainFit": fit.get("ideal_venture_type", "Various domains"),
            "expertiseFit": f"Best suited as {fit.get('ideal_role', 'Entrepreneur')} with {fit.get('overall_fit', 'Medium')} entrepreneurial fit",
            "successFactors": f"Focus on strengthening {', '.join(areas_dev[:2])} while leveraging {', '.join(strengths[:2])}",
        }

        return jsonify({
            "hasProfile": True,
            "userId": user_id,
            "evaluationId": str(eval_doc.get("_id", "")),
            "overallScore": overall_score,
            "profile": profile
        }), 200

    except Exception as e:
        logger.error(f"Failed to get psychometric profile: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Failed to retrieve profile", "details": str(e)}), 500


# =========================================================================
# 2. GET PSYCHOMETRIC STATUS
# =========================================================================

@psychometric_bp.route('/status', methods=['GET'])
@requires_auth()
def get_psychometric_status():
    """
    Check if user has completed psychometric assessment and get summary.
    
    Returns:
        {
            "success": bool,
            "isPsychometricAnalysisDone": bool,
            "score": float | null,
            "completedAt": str | null,
            "evaluationId": str | null
        }
    """
    try:
        user_id = request.user_id

        # Check if user has profile
        user_doc = users_coll.find_one(
            {"_id": user_id},
            {"isPsychometricAnalysisDone": 1, "psychometricScore": 1, "psychometricCompletedAt": 1}
        )

        if not user_doc:
            return jsonify({"error": "User not found"}), 404

        # Get evaluation ID if exists
        eval_doc = evaluations_coll.find_one(
            {"evaluation_result.user_id": user_id},
            {"_id": 1},
            sort=[("evaluation_result.evaluated_at", -1)]
        )

        return jsonify({
            "success": True,
            "isPsychometricAnalysisDone": user_doc.get("isPsychometricAnalysisDone", False),
            "score": user_doc.get("psychometricScore"),
            "completedAt": user_doc.get("psychometricCompletedAt"),
            "evaluationId": str(eval_doc.get("_id", "")) if eval_doc else None
        }), 200

    except Exception as e:
        logger.error(f"Failed to get psychometric status: {str(e)}")
        return jsonify({"error": str(e)}), 500


# =========================================================================
# 3. GET DETAILED ASSESSMENT RESULTS
# =========================================================================

@psychometric_bp.route('/results', methods=['GET'])
@requires_auth()
def get_psychometric_results():
    """Get full detailed psychometric assessment results."""
    try:
        user_id = request.user_id
        caller_role = getattr(request, "user_role", None)
        
        print("=" * 80)
        print("🔍 Fetching psychometric results")
        print(f"   User ID: {user_id}")
        print(f"   Role: {caller_role}")
        
        # Determine collection
        if caller_role in ["mentor", "internal_mentor", "external_mentor"]:
            print("   📚 Querying mentor_evaluations_coll")
            collection = mentor_evaluations_coll
            is_mentor = True
        else:
            print("   📚 Querying evaluations_coll (innovators)")
            collection = evaluations_coll
            is_mentor = False
        
        # Query with user_id as string, sort by most recent
        query = {"user_id": str(user_id)}
        
        # ✅ DEBUG: Check all documents for this user
        all_docs = list(collection.find(query).sort("created_at", -1))
        print(f"   📊 Found {len(all_docs)} total documents for this user")
        for idx, doc in enumerate(all_docs):
            print(f"      [{idx}] ID: {doc.get('_id')} | Score: {doc.get('overall_psychometric_score' if not is_mentor else 'overall_mentor_score', 0)} | Created: {doc.get('created_at')}")
        
        # Get the latest one
        eval_doc = collection.find_one(
            query,
            sort=[("created_at", -1)]
        )
        
        if not eval_doc:
            print(f"   ⚠️ No assessment found")
            return jsonify({
                "success": True,
                "data": None,
                "message": "No psychometric assessment completed yet"
            }), 200
        
        print(f"   ✅ Found assessment: {eval_doc.get('_id')}")
        print(f"   Document keys: {list(eval_doc.keys())}")
        print(f"   Raw scores: {eval_doc.get('psychometric_scores', {})}")
        print(f"   Overall score field value: {eval_doc.get('overall_psychometric_score' if not is_mentor else 'overall_mentor_score')}")
  
        # Build response
        if is_mentor:
            result_data = {
                "evaluationId": str(eval_doc.get("_id", "")),
                "userId": str(user_id),
                "profileType": "mentor",
                "userName": eval_doc.get("user_name", ""),
                "overallScore": eval_doc.get("overall_mentor_score", 0),
                "dimensionScores": eval_doc.get("psychometric_scores", {}),
                "strengths": eval_doc.get("top_strengths", []),
                "areasForDevelopment": eval_doc.get("development_areas", []),
                "personalityProfile": eval_doc.get("mentor_profile_summary", ""),
                "entrepreneurialFit": {
                    "overall_fit": eval_doc.get("mentoring_fit", ""),
                    "fit_score": eval_doc.get("fit_score", 0),
                    "mentoring_readiness": eval_doc.get("mentoring_readiness", ""),
                    "teaching_style": eval_doc.get("teaching_style", ""),
                    "mentoring_capacity": eval_doc.get("mentoring_capacity", ""),
                    "expertise_domains": eval_doc.get("expertise_domains", []),
                    "ideal_mentee_profile": eval_doc.get("ideal_mentee_profile", {})
                },
                "recommendations": eval_doc.get("recommendations", []),
                "detailedInsights": eval_doc.get("detailed_insights", {}),
                "completedAt": eval_doc.get("assessment_date", eval_doc.get("created_at")),
                "lastUpdated": eval_doc.get("last_updated"),
                "profileCompleteness": eval_doc.get("profile_completeness", 0),
                "questionsAnswered": 0,
                "completionRate": eval_doc.get("profile_completeness", 0)
            }
        else:
            # Innovator
            result_data = {
                "evaluationId": str(eval_doc.get("_id", "")),
                "userId": str(user_id),
                "profileType": "innovator",
                "userName": eval_doc.get("user_name", ""),
                "overallScore": eval_doc.get("overall_psychometric_score", 0),  # ✅ Correct field
                "dimensionScores": eval_doc.get("psychometric_scores", {}),
                "strengths": eval_doc.get("top_strengths", []),
                "areasForDevelopment": eval_doc.get("development_areas", []),
                "personalityProfile": eval_doc.get("personality_profile", ""),
                "entrepreneurialFit": {
                    "overall_fit": eval_doc.get("entrepreneurial_fit", ""),
                    "fit_score": eval_doc.get("fit_score", 0),
                    "ideal_role": eval_doc.get("ideal_role", ""),
                    "ideal_venture_type": eval_doc.get("ideal_venture_type", ""),
                    "risk_tolerance_level": eval_doc.get("risk_tolerance_level", ""),
                    "validation_focus_areas": eval_doc.get("validation_focus_areas", [])
                },
                "recommendations": eval_doc.get("recommendations", []),
                "detailedInsights": eval_doc.get("detailed_insights", {}),
                "completedAt": eval_doc.get("assessment_date", eval_doc.get("created_at")),
                "lastUpdated": eval_doc.get("last_updated"),
                "profileCompleteness": eval_doc.get("profile_completeness", 0),
                "questionsAnswered": 0,
                "completionRate": eval_doc.get("profile_completeness", 0)
            }
        
        print(f"   ✅ Returning score: {result_data['overallScore']}")
        print("=" * 80)
        
        return jsonify({
            "success": True,
            "data": result_data
        }), 200
    
    except Exception as e:
        print(f"   ❌ ERROR: {str(e)}")
        logger.error(f"Failed to get psychometric results: {str(e)}")
        logger.error(traceback.format_exc())
        print("=" * 80)
        return jsonify({"error": str(e)}), 500

# =========================================================================
# 4. GET DIMENSION BREAKDOWN (for charts)
# =========================================================================

@psychometric_bp.route('/dimensions', methods=['GET'])
@requires_auth()
def get_dimension_breakdown():
    """
    Get dimension/attribute scores breakdown for charting.
    
    Returns:
        {
            "success": bool,
            "data": {
                "overallScore": float,
                "dimensions": [
                    {"dimension": str, "score": float, "status": str},
                    ...
                ],
                "completedAt": str
            }
        }
    """
    try:
        user_id = request.user_id

        # Get latest evaluation
        eval_doc = evaluations_coll.find_one(
            {"evaluation_result.user_id": user_id},
            sort=[("evaluation_result.evaluated_at", -1)]
        )

        if not eval_doc:
            return jsonify({"error": "No assessment found"}), 404

        eval_result = eval_doc.get("evaluation_result", {})
        dim_scores = eval_result.get("dimension_scores", {})

        # Format dimensions with status
        dimensions = []
        for dimension, score in dim_scores.items():
            if score >= 8:
                status = "Excellent"
            elif score >= 6:
                status = "Good"
            elif score >= 4:
                status = "Moderate"
            else:
                status = "Needs Improvement"

            dimensions.append({
                "dimension": dimension.replace("_", " ").title(),
                "score": score,
                "status": status
            })

        # Sort by score descending
        dimensions.sort(key=lambda x: x["score"], reverse=True)

        return jsonify({
            "success": True,
            "data": {
                "overallScore": eval_result.get("overall_score", 0),
                "dimensions": dimensions,
                "completedAt": eval_result.get("evaluated_at")
            }
        }), 200

    except Exception as e:
        logger.error(f"Failed to get dimension breakdown: {str(e)}")
        return jsonify({"error": str(e)}), 500


# =========================================================================
# 5. TEAM COMPATIBILITY (Read-only, no LLM)
# =========================================================================

@psychometric_bp.route('/team-compatibility', methods=['POST'])
@requires_auth()
def check_team_compatibility():
    """
    Calculate team compatibility based on stored psychometric profiles.
    Computes compatibility score across multiple team members.
    
    Request:
        {
            "userIds": [str, str, ...]
        }
    
    Returns:
        {
            "success": bool,
            "compatibility": {
                "overallScore": float,
                "teamMembers": [
                    {
                        "userId": str,
                        "name": str,
                        "strengths": [str],
                        "complementary": bool
                    },
                    ...
                ],
                "synergies": [str],
                "potentialConflicts": [str]
            }
        }
    """
    try:
        body = request.get_json(force=True)
        user_ids = body.get("userIds", [])

        if len(user_ids) < 2:
            return jsonify({"error": "Need at least 2 team members"}), 400
            
        try:
            user_ids = [ObjectId(uid) if isinstance(uid, str) else uid for uid in user_ids]
        except:
            return jsonify({"error": "Invalid user IDs"}), 400


        logger.info(f"Computing team compatibility for: {user_ids}")

        team_data = []
        all_strengths = []
        all_weaknesses = []

        # Get latest evaluation for each user
        for uid in user_ids:
            eval_doc = evaluations_coll.find_one(
                {"evaluation_result.user_id": uid},
                sort=[("evaluation_result.evaluated_at", -1)]
            )

            if not eval_doc:
                continue

            eval_result = eval_doc.get("evaluation_result", {})
            strengths = eval_result.get("strengths", [])
            weaknesses = eval_result.get("areas_for_development", [])

            user_doc = users_coll.find_one({"_id": uid}, {"name": 1})

            team_data.append({
                "userId": uid,
                "name": user_doc.get("name", "Unknown") if user_doc else "Unknown",
                "strengths": strengths,
                "weaknesses": weaknesses
            })

            all_strengths.extend(strengths)
            all_weaknesses.extend(weaknesses)

        if not team_data:
            return jsonify({"error": "No assessments found for team members"}), 404

        # Analyze synergies: one's strength can offset another's weakness
        synergies = []
        for member in team_data:
            for strength in member.get("strengths", []):
                for other in team_data:
                    if other["userId"] != member["userId"]:
                        if strength in other.get("weaknesses", []):
                            synergies.append(
                                f"{member['name']}'s {strength.lower()} complements {other['name']}"
                            )

        # Detect potential conflicts: shared weaknesses
        potential_conflicts = []
        weakness_counts = {}
        for weakness in all_weaknesses:
            weakness_counts[weakness] = weakness_counts.get(weakness, 0) + 1

        for weakness, count in weakness_counts.items():
            if count >= 2:
                potential_conflicts.append(f"Multiple members need work on: {weakness}")

        # Compute overall compatibility (0-10)
        synergy_score = min(len(synergies) * 2, 10)
        conflict_penalty = len(potential_conflicts) * 2
        overall_score = max(0, min(10, synergy_score - conflict_penalty))

        return jsonify({
            "success": True,
            "compatibility": {
                "overallScore": overall_score,
                "teamMembers": team_data,
                "synergies": synergies[:5],  # Top 5
                "potentialConflicts": potential_conflicts[:3]  # Top 3
            }
        }), 200

    except Exception as e:
        logger.error(f"Failed to compute team compatibility: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


# =========================================================================
# 6. ADMIN: LIST ALL ASSESSMENTS
# =========================================================================

@psychometric_bp.route('/assessments', methods=['GET'])
@requires_role(["ttc_coordinator", "college_admin", "super_admin"])
def get_all_assessments():
    """
    List all psychometric assessments (admin/coordinator only).
    Filters based on coordinator/admin role and scope.
    
    Query params:
        - limit: int (default 50)
        - skip: int (default 0)
    
    Returns:
        {
            "success": bool,
            "data": [
                {
                    "evaluationId": str,
                    "userId": str,
                    "userName": str,
                    "userEmail": str,
                    "overallScore": float,
                    "completedAt": str
                },
                ...
            ],
            "total": int
        }
    """
    try:
        caller_id = request.user_id
        caller_role = getattr(request, "user_role", None)
        limit = int(request.args.get("limit", 50))
        skip = int(request.args.get("skip", 0))

        # Build query based on role
        query = {}
        if caller_role == "ttc_coordinator":
            # Get innovators under this coordinator
            innovator_ids = users_coll.distinct(
                "_id",
                {"createdBy": caller_id, "role": "innovator"}
            )
            query = {"evaluation_result.user_id": {"$in": innovator_ids}}

        elif caller_role == "college_admin":
            # Get all users in this college
            user_ids = users_coll.distinct(
                "_id",
                {"collegeId": caller_id}
            )
            query = {"evaluation_result.user_id": {"$in": user_ids}}

        # super_admin gets all

        # Get total count
        total = evaluations_coll.count_documents(query)

        # Get paginated results
        cursor = (
            evaluations_coll.find(query)
            .sort("evaluation_result.evaluated_at", -1)
            .skip(skip)
            .limit(limit)
        )

        assessments = []
        for doc in cursor:
            eval_result = doc.get("evaluation_result", {})
            user_id = eval_result.get("user_id")

            user_doc = users_coll.find_one(
                {"_id": user_id},
                {"name": 1, "email": 1}
            )

            assessments.append({
                "evaluationId": str(doc.get("_id", "")),
                "userId": user_id,
                "userName": user_doc.get("name", "Unknown") if user_doc else "Unknown",
                "userEmail": user_doc.get("email", "") if user_doc else "",
                "overallScore": eval_result.get("overall_score", 0),
                "completedAt": eval_result.get("evaluated_at")
            })

        return jsonify({
            "success": True,
            "data": assessments,
            "total": total,
            "limit": limit,
            "skip": skip
        }), 200

    except Exception as e:
        logger.error(f"Failed to get assessments: {str(e)}")
        return jsonify({"error": str(e)}), 500


# =========================================================================
# 7. ADMIN: DELETE ASSESSMENT
# =========================================================================

@psychometric_bp.route('/assessments/<user_id>', methods=['DELETE'])
@requires_role(["super_admin"])
def delete_assessment(user_id):
    """
    Delete all psychometric assessments for a user (super admin only).
    Also resets user flags.
    
    Returns:
        {
            "success": bool,
            "message": str,
            "deletedCount": int
        }
    """
    try:
        if isinstance(user_id, str):
            user_id = ObjectId(user_id)
    except:
        return jsonify({"error": "Invalid user ID"}), 400

    try:
        logger.info(f"Deleting assessments for user: {user_id}")

        # Delete all evaluations for this user
        result = evaluations_coll.delete_many(
            {"evaluation_result.user_id": user_id}
        )

        # Reset user flags
        users_coll.update_one(
            {"_id": user_id},
            {
                "$set": {
                    "isPsychometricAnalysisDone": False,
                    "psychometricScore": None,
                    "psychometricCompletedAt": None
                }
            }
        )

        logger.info(f"Deleted {result.deleted_count} evaluations for user {user_id}")

        return jsonify({
            "success": True,
            "message": f"Deleted {result.deleted_count} assessment(s)",
            "deletedCount": result.deleted_count
        }), 200

    except Exception as e:
        logger.error(f"Failed to delete assessment: {str(e)}")
        return jsonify({"error": str(e)}), 500


# =========================================================================
# 8. ADMIN: EXPORT ASSESSMENT DATA
# =========================================================================

@psychometric_bp.route('/export', methods=['GET'])
@requires_role(["ttc_coordinator", "college_admin", "super_admin"])
def export_assessment_data():
    """
    Export psychometric data as summary (for reporting/analytics).
    
    Returns:
        {
            "success": bool,
            "data": [
                {
                    "userId": str,
                    "name": str,
                    "overallScore": float,
                    "topStrengths": [str],
                    "areasForGrowth": [str],
                    "entrepreneurialFit": str,
                    "completedAt": str
                },
                ...
            ]
        }
    """
    try:
        caller_id = request.user_id
        caller_role = getattr(request, "user_role", None)

        # Build query
        query = {}
        if caller_role == "ttc_coordinator":
            innovator_ids = users_coll.distinct(
                "_id",
                {"createdBy": caller_id, "role": "innovator"}
            )
            query = {"evaluation_result.user_id": {"$in": innovator_ids}}
        elif caller_role == "college_admin":
            user_ids = users_coll.distinct(
                "_id",
                {"collegeId": caller_id}
            )
            query = {"evaluation_result.user_id": {"$in": user_ids}}

        cursor = evaluations_coll.find(query).sort("evaluation_result.evaluated_at", -1)

        export_data = []
        for doc in cursor:
            eval_result = doc.get("evaluation_result", {})
            user_id = eval_result.get("user_id")

            user_doc = users_coll.find_one(
                {"_id": user_id},
                {"name": 1}
            )

            export_data.append({
                "userId": user_id,
                "name": user_doc.get("name", "Unknown") if user_doc else "Unknown",
                "overallScore": eval_result.get("overall_score", 0),
                "topStrengths": eval_result.get("strengths", [])[:3],
                "areasForGrowth": eval_result.get("areas_for_development", [])[:3],
                "entrepreneurialFit": eval_result.get("entrepreneurial_fit", {}).get("overall_fit", "Unknown"),
                "completedAt": eval_result.get("evaluated_at")
            })

        return jsonify({
            "success": True,
            "data": export_data
        }), 200

    except Exception as e:
        logger.error(f"Failed to export assessment data: {str(e)}")
        return jsonify({"error": str(e)}), 500
