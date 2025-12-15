from flask import Blueprint, request, jsonify
from app.database.mongo import ideas_coll, users_coll
from app.middleware.auth import requires_auth, requires_role
from app.utils.validators import clean_doc
from bson import ObjectId
from app.utils.validators import normalize_user_id, normalize_any_id_field, clean_doc, get_user_by_any_id
from app.utils.id_helpers import find_user, ids_match


analytics_bp = Blueprint('analytics', __name__, url_prefix='/api/analytics')


# -------------------------------------------------------------------------
# 1. DOMAIN TREND - Shows idea distribution by domain
# -------------------------------------------------------------------------
@analytics_bp.route('/domain-trend', methods=['GET'])
@requires_auth()
def domain_trend():
    """Domain-wise idea counts"""
    caller = request.token_payload
    caller_role = caller.get('role')
    caller_id = caller.get('uid')
    
    # Build match stage based on role
    if caller_role == 'ttc_coordinator':
        # Only ideas created by innovators under this coordinator
        innovator_ids = users_coll.distinct("_id", {"createdBy": caller_id, "role": "innovator"})
        match_stage = {"userId": {"$in": [str(uid) for uid in innovator_ids]}, "isDeleted": {"$ne": True}}
    elif caller_role in ['college_admin', 'super_admin']:
        match_stage = {"isDeleted": {"$ne": True}}
    elif caller_role == 'innovator':
        # Only caller's own ideas
        match_stage = {"userId": caller_id, "isDeleted": {"$ne": True}}
    else:
        return jsonify({"error": "Unknown role"}), 403
    
    pipeline = [
        {"$match": match_stage},
        {"$group": {"_id": "$domain", "ideas": {"$sum": 1}}},
        {"$sort": {"ideas": -1}},
        {"$project": {"_id": 0, "name": "$_id", "ideas": 1}}
    ]
    
    data = list(ideas_coll.aggregate(pipeline))
    return jsonify({"success": True, "data": data}), 200


# -------------------------------------------------------------------------
# 2. COLLEGE-SPECIFIC DOMAIN TREND
# -------------------------------------------------------------------------
@analytics_bp.route('/college/domain-trend/<collegeId>', methods=['GET'])
@requires_role(['college_admin'])
def college_domain_trend(collegeId):
    """Domain trend for specific college"""
    try:
        if isinstance(collegeId, str):
            collegeId = ObjectId(collegeId)
    except:
        return jsonify({"error": "Invalid college ID"}), 400

    caller_id = request.user_id
    
    print("caller_id:", caller_id)
    print("collegeId param:", collegeId)
    
    pipeline = [
        {"$match": {"collegeId": collegeId, "isDeleted": {"$ne": True}}},
        {"$group": {"_id": "$domain", "ideas": {"$sum": 1}}},
        {"$sort": {"ideas": -1}},
        {"$project": {"_id": 0, "name": "$_id", "ideas": 1}}
    ]
    
    data = list(ideas_coll.aggregate(pipeline))
    return jsonify({"success": True, "data": data}), 200


# -------------------------------------------------------------------------
# 3. IDEA QUALITY TREND - Monthly average scores
# -------------------------------------------------------------------------
@analytics_bp.route('/idea-quality-trend', methods=['GET'])
@requires_role(['ttc_coordinator', 'college_admin'])
def idea_quality_trend():
    """Monthly idea quality trends"""
    caller = request.token_payload
    role = caller.get('role')
    caller_id = caller.get('uid')
    
    # Get innovator IDs based on role
    if role == 'ttc_coordinator':
        innovator_ids = users_coll.distinct("_id", {"createdBy": caller_id, "role": "innovator"})
    else:  # college_admin
        innovator_ids = users_coll.distinct("_id", {"collegeId": caller_id, "role": "innovator"})
    
    pipeline = [
        {"$match": {"userId": {"$in": [str(uid) for uid in innovator_ids]}, "isDeleted": {"$ne": True}}},
        {"$addFields": {
            "month": {"$dateToString": {"format": "%b", "date": "$createdAt"}}
        }},
        {"$group": {
            "_id": "$month",
            "quality": {"$avg": "$overallScore"}
        }},
        {"$sort": {"_id": 1}}
    ]
    
    raw = list(ideas_coll.aggregate(pipeline))
    
    # Format with standard month order
    month_order = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    mapped = {m['_id']: round(m['quality'], 2) for m in raw}
    data = [{"month": m, "quality": mapped.get(m, 0)} for m in month_order]
    
    return jsonify({"success": True, "data": data}), 200


# -------------------------------------------------------------------------
# 4. CATEGORY SUCCESS - Ideas by approval status per domain
# -------------------------------------------------------------------------
@analytics_bp.route('/category-success', methods=['GET'])
@requires_role(['ttc_coordinator', 'college_admin'])
def category_success():
    """Success breakdown by domain"""
    caller = request.token_payload
    role = caller.get('role')
    caller_id = caller.get('uid')
    
    # Get innovator IDs
    if role == 'ttc_coordinator':
        innovator_ids = users_coll.distinct("_id", {"createdBy": caller_id, "role": "innovator"})
    else:  # college_admin
        innovator_ids = users_coll.distinct("_id", {"collegeId": caller_id, "role": "innovator"})
    
    pipeline = [
        {"$match": {"userId": {"$in": [str(uid) for uid in innovator_ids]}, "isDeleted": {"$ne": True}}},
        {"$group": {
            "_id": "$domain",
            "approved": {"$sum": {"$cond": [{"$gte": ["$overallScore", 80]}, 1, 0]}},
            "moderate": {"$sum": {"$cond": [{"$and": [
                {"$gte": ["$overallScore", 50]},
                {"$lt": ["$overallScore", 80]}
            ]}, 1, 0]}},
            "rejected": {"$sum": {"$cond": [{"$lt": ["$overallScore", 50]}, 1, 0]}}
        }},
        {"$project": {
            "_id": 0,
            "category": "$_id",
            "approved": 1,
            "moderate": 1,
            "rejected": 1
        }}
    ]
    
    data = list(ideas_coll.aggregate(pipeline))
    return jsonify({"success": True, "data": data}), 200


# -------------------------------------------------------------------------
# 5. TOP INNOVATORS - Highest scoring innovators
# -------------------------------------------------------------------------
@analytics_bp.route('/top-innovators', methods=['GET'])
@requires_role(['ttc_coordinator', 'college_admin'])
def top_innovators():
    """Top 5 performing innovators"""
    caller_id = request.user_id
    caller_role = request.user_role
    
    # Get innovator IDs based on role
    if caller_role == 'ttc_coordinator':
        innovator_ids = users_coll.distinct("_id", {"createdBy": caller_id, "role": "innovator"})
    elif caller_role == 'college_admin':
        innovator_ids = users_coll.distinct("_id", {"collegeId": caller_id, "role": "innovator"})
    else:
        return jsonify([]), 200
    
    # Defensive check
    if not innovator_ids:
        return jsonify([]), 200
    
    pipeline = [
        {"$match": {"userId": {"$in": [str(uid) for uid in innovator_ids]}, "isDeleted": {"$ne": True}}},
        {"$group": {
            "_id": "$userId",
            "avgScore": {"$avg": "$overallScore"},
            "ideaCount": {"$sum": 1}
        }},
        {"$sort": {"avgScore": -1}},
        {"$limit": 5},
        {"$lookup": {
            "from": "users",
            "localField": "_id",
            "foreignField": "_id",
            "as": "user"
        }},
        {"$unwind": "$user"},
        {"$project": {
            "_id": 0,
            "name": "$user.name",
            "score": "$avgScore"
        }}
    ]
    
    data = list(ideas_coll.aggregate(pipeline))
    return jsonify(data), 200


# -------------------------------------------------------------------------
# 6. REJECTION REASONS - Most common rejection criteria
# -------------------------------------------------------------------------
@analytics_bp.route('/rejection-reasons', methods=['GET'])
@requires_role(['ttc_coordinator', 'college_admin'])
def rejection_reasons():
    """Top 4 rejection reasons"""
    caller = request.token_payload
    role = caller.get('role')
    caller_id = caller.get('uid')
    
    # Get innovator IDs
    if role == 'ttc_coordinator':
        innovator_ids = users_coll.distinct("_id", {"createdBy": caller_id, "role": "innovator"})
    else:  # college_admin
        innovator_ids = users_coll.distinct("_id", {"collegeId": caller_id, "role": "innovator"})
    
    pipeline = [
        {"$match": {
            "userId": {"$in": [str(uid) for uid in innovator_ids]},
            "overallScore": {"$lt": 50},
            "isDeleted": {"$ne": True}
        }},
        {"$unwind": "$evaluatedData"},
        {"$match": {"evaluatedData.score": {"$lt": 50}}},
        {"$group": {
            "_id": "$evaluatedData.criterion",
            "value": {"$sum": 1}
        }},
        {"$sort": {"value": -1}},
        {"$limit": 4},
        {"$project": {
            "_id": 0,
            "name": "$_id",
            "value": 1,
            "fill": {
                "$switch": {
                    "branches": [
                        {"case": {"$eq": ["$_id", "Low Market Need"]}, "then": "hsl(var(--color-rejected))"},
                        {"case": {"$eq": ["$_id", "Technical Feasibility"]}, "then": "hsl(var(--chart-3))"},
                        {"case": {"$eq": ["$_id", "Weak Business Model"]}, "then": "hsl(var(--chart-5))"},
                        {"case": {"$eq": ["$_id", "Poor Team Fit"]}, "then": "hsl(var(--muted))"}
                    ],
                    "default": "hsl(var(--muted))"
                }
            }
        }}
    ]
    
    data = list(ideas_coll.aggregate(pipeline))
    
    # If no rejections, return placeholder
    if not data:
        data = [{"name": "No rejections yet", "value": 1, "fill": "hsl(var(--muted))"}]
    
    return jsonify({"success": True, "data": data}), 200


# -------------------------------------------------------------------------
# 7. INNOVATOR ENGAGEMENT - Active vs Invited innovators
# -------------------------------------------------------------------------
@analytics_bp.route('/innovator-engagement', methods=['GET'])
@requires_role(['ttc_coordinator', 'college_admin'])
def innovator_engagement():
    """Active vs invited innovators"""
    caller = request.token_payload
    role = caller.get('role')
    caller_id = caller.get('uid')
    
    # Get innovator IDs based on role
    if role == 'ttc_coordinator':
        innovator_ids = users_coll.distinct("_id", {"createdBy": caller_id, "role": "innovator"})
    else:  # college_admin
        innovator_ids = users_coll.distinct("_id", {"collegeId": caller_id, "role": "innovator"})
    
    # Count active vs invited
    active_cnt = users_coll.count_documents({
        "_id": {"$in": innovator_ids},
        "isActive": True,
        "isDeleted": {"$ne": True}
    })
    
    invited_cnt = len(innovator_ids) - active_cnt
    
    data = [
        {"name": "Active Innovators", "value": active_cnt, "fill": "hsl(var(--chart-1))"},
        {"name": "Invited Innovators", "value": invited_cnt, "fill": "hsl(var(--chart-5))"}
    ]
    
    return jsonify({"success": True, "data": data}), 200


# Add to analytics.py

# -------------------------------------------------------------------------
# 8. INNOVATOR PERSONAL STATS - Overview metrics for innovator's dashboard
# -------------------------------------------------------------------------
@analytics_bp.route('/innovator/stats', methods=['GET'])
@requires_role(['innovator', 'individual_innovator'])
def innovator_personal_stats():
    """Get personal statistics for the logged-in innovator"""
    caller_id = request.user_id
    
    # Get all ideas for this innovator
    ideas = list(ideas_coll.find({
        "innovatorId": caller_id,
        "isDeleted": {"$ne": True}
    }))
    
    # Calculate stats
    total_ideas = len(ideas)
    validated_ideas = [idea for idea in ideas if idea.get('overallScore') is not None]
    
    # Average score
    average_score = 0
    if validated_ideas:
        average_score = sum(idea['overallScore'] for idea in validated_ideas) / len(validated_ideas)
    
    # Approval rate (score >= 80)
    approved_count = sum(1 for idea in validated_ideas if idea.get('overallScore', 0) >= 80)
    approval_rate = (approved_count / total_ideas * 100) if total_ideas > 0 else 0
    
    # Ideas by status
    status_breakdown = {}
    for idea in ideas:
        status = idea.get('status', 'submitted')
        status_breakdown[status] = status_breakdown.get(status, 0) + 1
    
    return jsonify({
        "success": True,
        "data": {
            "totalIdeas": total_ideas,
            "averageScore": round(average_score, 2),
            "approvalRate": round(approval_rate, 2),
            "approvedCount": approved_count,
            "validatedCount": len(validated_ideas),
            "statusBreakdown": status_breakdown
        }
    }), 200


# -------------------------------------------------------------------------
# 9. INNOVATOR SCORE OVER TIME - Track improvement
# -------------------------------------------------------------------------
@analytics_bp.route('/innovator/score-timeline', methods=['GET'])
@requires_role(['innovator', 'individual_innovator'])
def innovator_score_timeline():
    """Get score progression over time for the innovator"""
    caller_id = request.user_id
    
    # Get ideas sorted by submission date
    pipeline = [
        {
            "$match": {
                "innovatorId": caller_id,
                "overallScore": {"$exists": True, "$ne": None},
                "isDeleted": {"$ne": True}
            }
        },
        {
            "$sort": {"submittedAt": 1}
        },
        {
            "$project": {
                "_id": 0,
                "ideaId": "$_id",
                "name": "$title",
                "date": {
                    "$dateToString": {
                        "format": "%Y-%m-%d",
                        "date": "$submittedAt"
                    }
                },
                "score": "$overallScore"
            }
        }
    ]
    
    data = list(ideas_coll.aggregate(pipeline))
    
    return jsonify({
        "success": True,
        "data": data
    }), 200


# -------------------------------------------------------------------------
# 10. INNOVATOR CLUSTER PERFORMANCE - Spider chart data
# -------------------------------------------------------------------------
@analytics_bp.route('/innovator/cluster-performance', methods=['GET'])
@requires_role(['innovator', 'individual_innovator'])
def innovator_cluster_performance():
    """Get average cluster scores for the innovator"""
    caller_id = request.user_id
    
    # Get all validated ideas
    ideas = list(ideas_coll.find({
        "innovatorId": caller_id,
        "clusterScores": {"$exists": True},
        "isDeleted": {"$ne": True}
    }))
    
    if not ideas:
        # Return default structure with 0 scores
        return jsonify({
            "success": True,
            "data": {
                "Core Idea & Innovation": 0,
                "Market & Commercial Opportunity": 0,
                "Execution & Operations": 0,
                "Business Model & Strategy": 0,
                "Team & Organizational Health": 0,
                "External Environment & Compliance": 0,
                "Risk & Future Outlook": 0
            }
        }), 200
    
    # Aggregate cluster scores
    cluster_totals = {}
    cluster_counts = {}
    
    for idea in ideas:
        cluster_scores = idea.get('clusterScores', {})
        for cluster_name, score in cluster_scores.items():
            if score is not None:
                cluster_totals[cluster_name] = cluster_totals.get(cluster_name, 0) + score
                cluster_counts[cluster_name] = cluster_counts.get(cluster_name, 0) + 1
    
    # Calculate averages
    avg_cluster_scores = {}
    for cluster_name in cluster_totals:
        avg_cluster_scores[cluster_name] = round(
            cluster_totals[cluster_name] / cluster_counts[cluster_name], 
            2
        )
    
    return jsonify({
        "success": True,
        "data": avg_cluster_scores
    }), 200


# -------------------------------------------------------------------------
# 11. INNOVATOR IDEAS LIST - All ideas with scores
# -------------------------------------------------------------------------
@analytics_bp.route('/innovator/ideas', methods=['GET'])
@requires_role(['innovator', 'individual_innovator'])
def innovator_ideas_list():
    """Get list of all ideas with basic info and scores"""
    caller_id = request.user_id
    
    # Pagination
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 10))
    skip = (page - 1) * limit
    
    # Get total count
    total = ideas_coll.count_documents({
        "innovatorId": caller_id,
        "isDeleted": {"$ne": True}
    })
    
    # Get ideas
    pipeline = [
        {
            "$match": {
                "innovatorId": caller_id,
                "isDeleted": {"$ne": True}
            }
        },
        {
            "$sort": {"submittedAt": -1}
        },
        {
            "$skip": skip
        },
        {
            "$limit": limit
        },
        {
            "$project": {
                "_id": 1,
                "title": 1,
                "domain": 1,
                "status": 1,
                "overallScore": 1,
                "submittedAt": 1,
                "mentorName": 1
            }
        }
    ]
    
    ideas = list(ideas_coll.aggregate(pipeline))
    
    # Clean IDs
    for idea in ideas:
        idea['id'] = idea.pop('_id')
    
    return jsonify({
        "success": True,
        "data": ideas,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit
        }
    }), 200

# -------------------------------------------------------------------------
# 12. TTC PERFORMANCE - Compare TTCs within college
# -------------------------------------------------------------------------
@analytics_bp.route('/college/ttc-performance', methods=['GET'])
@requires_role(['college_admin'])
def college_ttc_performance():
    """Get performance comparison of TTCs in the college"""
    caller_id = request.user_id
    
    # Get caller's college
    caller_user = users_coll.find_one({"_id": caller_id}, {"collegeId": 1})
    if not caller_user or not caller_user.get('collegeId'):
        return jsonify({"success": True, "data": []}), 200
    
    college_id = caller_user['collegeId']
    
    # Get all TTCs in this college
    ttcs = list(users_coll.find({
        "collegeId": college_id,
        "role": "ttc_coordinator",
        "isDeleted": {"$ne": True}
    }, {"_id": 1, "name": 1}))
    
    if not ttcs:
        return jsonify({"success": True, "data": []}), 200
    
    # Get performance for each TTC
    performance_data = []
    
    for ttc in ttcs:
        # Get innovators under this TTC
        innovator_ids = users_coll.distinct("_id", {
            "ttcCoordinatorId": ttc['_id'],
            "role": "innovator",
            "isDeleted": {"$ne": True}
        })
        
        # Get ideas from these innovators
        ideas = list(ideas_coll.find({
            "innovatorId": {"$in": [str(uid) for uid in innovator_ids]},
            "isDeleted": {"$ne": True}
        }))
        
        total_ideas = len(ideas)
        approved_ideas = sum(1 for idea in ideas if idea.get('overallScore', 0) >= 80)
        approval_rate = (approved_ideas / total_ideas * 100) if total_ideas > 0 else 0
        
        performance_data.append({
            "ttcId": ttc['_id'],
            "name": ttc['name'],
            "ideas": total_ideas,
            "approved": approved_ideas,
            "approvalRate": round(approval_rate, 2)
        })
    
    # Sort by ideas count
    performance_data.sort(key=lambda x: x['ideas'], reverse=True)
    
    return jsonify({
        "success": True,
        "data": performance_data
    }), 200


# -------------------------------------------------------------------------
# 13. COLLEGE SUMMARY STATS - Overview for college admin
# -------------------------------------------------------------------------
@analytics_bp.route('/college/summary', methods=['GET'])
@requires_role(['college_admin'])
def college_summary():
    """Get summary statistics for college admin dashboard"""
    caller_id = request.user_id
    
    # Get caller's college
    caller_user = users_coll.find_one({"_id": caller_id}, {"collegeId": 1})
    if not caller_user or not caller_user.get('collegeId'):
        return jsonify({"success": True, "data": {}}), 200
    
    college_id = caller_user['collegeId']
    
    # Count TTCs
    ttc_count = users_coll.count_documents({
        "collegeId": college_id,
        "role": "ttc_coordinator",
        "isDeleted": {"$ne": True}
    })
    
    # Get all innovators in college
    innovator_ids = users_coll.distinct("_id", {
        "collegeId": college_id,
        "role": "innovator",
        "isDeleted": {"$ne": True}
    })
    
    # Get all ideas from college innovators
    ideas = list(ideas_coll.find({
        "innovatorId": {"$in": [str(uid) for uid in innovator_ids]},
        "isDeleted": {"$ne": True}
    }))
    
    total_ideas = len(ideas)
    approved_ideas = sum(1 for idea in ideas if idea.get('overallScore', 0) >= 80)
    approval_rate = (approved_ideas / total_ideas * 100) if total_ideas > 0 else 0
    
    # Status breakdown
    status_counts = {}
    for idea in ideas:
        status = idea.get('status', 'unknown')
        status_counts[status] = status_counts.get(status, 0) + 1
    
    return jsonify({
        "success": True,
        "data": {
            "totalTTCs": ttc_count,
            "totalInnovators": len(innovator_ids),
            "totalIdeas": total_ideas,
            "approvedIdeas": approved_ideas,
            "approvalRate": round(approval_rate, 2),
            "statusBreakdown": status_counts
        }
    }), 200

# -------------------------------------------------------------------------
# 14. SUPER ADMIN - Domain Approval Rates (System-wide)
# -------------------------------------------------------------------------
@analytics_bp.route('/admin/domain-approval-rates', methods=['GET'])
@requires_role(['super_admin'])
def admin_domain_approval_rates():
    """Get approval rates by domain across entire system"""
    
    pipeline = [
        {"$match": {"isDeleted": {"$ne": True}}},
        {"$group": {
            "_id": "$domain",
            "totalIdeas": {"$sum": 1},
            "approvedIdeas": {
                "$sum": {"$cond": [{"$gte": ["$overallScore", 80]}, 1, 0]}
            },
            "avgScore": {"$avg": "$overallScore"}
        }},
        {"$project": {
            "_id": 0,
            "domain": "$_id",
            "totalIdeas": 1,
            "approvedIdeas": 1,
            "approvalRate": {
                "$multiply": [
                    {"$divide": ["$approvedIdeas", "$totalIdeas"]},
                    100
                ]
            },
            "avgScore": {"$round": ["$avgScore", 2]}
        }},
        {"$sort": {"approvalRate": -1}}
    ]
    
    data = list(ideas_coll.aggregate(pipeline))
    
    return jsonify({
        "success": True,
        "data": data
    }), 200


# -------------------------------------------------------------------------
# 15. SUPER ADMIN - College Submissions Distribution
# -------------------------------------------------------------------------
@analytics_bp.route('/admin/college-distribution', methods=['GET'])
@requires_role(['super_admin'])
def admin_college_distribution():
    """Get idea submission distribution across colleges"""
    
    # Get all colleges
    colleges = list(users_coll.find(
        {"role": "college_admin", "isDeleted": {"$ne": True}},
        {"_id": 1, "name": 1, "collegeId": 1}
    ))
    
    college_data = []
    colors = [
        "hsl(var(--chart-1))",
        "hsl(var(--chart-2))",
        "hsl(var(--chart-3))",
        "hsl(var(--chart-4))",
        "hsl(var(--chart-5))",
    ]
    
    for idx, college in enumerate(colleges):
        # Get innovators from this college
        college_id = college.get('collegeId') or college['_id']
        
        innovator_ids = users_coll.distinct("_id", {
            "collegeId": college_id,
            "role": "innovator",
            "isDeleted": {"$ne": True}
        })
        
        # Count ideas
        idea_count = ideas_coll.count_documents({
            "innovatorId": {"$in": [str(uid) for uid in innovator_ids]},
            "isDeleted": {"$ne": True}
        })
        
        if idea_count > 0:  # Only include colleges with ideas
            college_data.append({
                "name": college.get('name', 'Unknown College'),
                "submissions": idea_count,
                "fill": colors[idx % len(colors)]
            })
    
    # Sort by submissions
    college_data.sort(key=lambda x: x['submissions'], reverse=True)
    
    return jsonify({
        "success": True,
        "data": college_data
    }), 200


# -------------------------------------------------------------------------
# 16. SUPER ADMIN - System Summary
# -------------------------------------------------------------------------
@analytics_bp.route('/admin/summary', methods=['GET'])
@requires_role(['super_admin'])
def admin_summary():
    """Get system-wide summary statistics"""
    
    # Count entities
    total_colleges = users_coll.count_documents({
        "role": "college_admin",
        "isDeleted": {"$ne": True}
    })
    
    total_ttcs = users_coll.count_documents({
        "role": "ttc_coordinator",
        "isDeleted": {"$ne": True}
    })
    
    total_innovators = users_coll.count_documents({
        "role": "innovator",
        "isDeleted": {"$ne": True}
    })
    
    total_mentors = users_coll.count_documents({
        "role": "internal_mentor",
        "isDeleted": {"$ne": True}
    })
    
    # Ideas stats
    total_ideas = ideas_coll.count_documents({"isDeleted": {"$ne": True}})
    
    # Get ideas with scores
    ideas_with_scores = list(ideas_coll.find(
        {"overallScore": {"$exists": True, "$ne": None}, "isDeleted": {"$ne": True}},
        {"overallScore": 1, "submittedAt": 1, "updatedAt": 1}
    ))
    
    approved_ideas = sum(1 for idea in ideas_with_scores if idea.get('overallScore', 0) >= 80)
    approval_rate = (approved_ideas / total_ideas * 100) if total_ideas > 0 else 0
    
    avg_score = sum(idea.get('overallScore', 0) for idea in ideas_with_scores) / len(ideas_with_scores) if ideas_with_scores else 0
    
    # Calculate validation times (in days)
    validation_times = []
    for idea in ideas_with_scores:
        if idea.get('submittedAt') and idea.get('updatedAt'):
            submitted = idea['submittedAt']
            updated = idea['updatedAt']
            delta = (updated - submitted).days
            if delta >= 0:  # Only positive values
                validation_times.append(delta)
    
    avg_validation_time = sum(validation_times) / len(validation_times) if validation_times else 0
    max_validation_time = max(validation_times) if validation_times else 0
    min_validation_time = min(validation_times) if validation_times else 0
    
    return jsonify({
        "success": True,
        "data": {
            "totalColleges": total_colleges,
            "totalTTCs": total_ttcs,
            "totalInnovators": total_innovators,
            "totalMentors": total_mentors,
            "totalIdeas": total_ideas,
            "approvedIdeas": approved_ideas,
            "approvalRate": round(approval_rate, 2),
            "avgScore": round(avg_score, 2),
            "validationMetrics": {
                "avgDays": round(avg_validation_time, 1),
                "maxDays": max_validation_time,
                "minDays": min_validation_time
            }
        }
    }), 200


# -------------------------------------------------------------------------
# 17. SUPER ADMIN - Export Data
# -------------------------------------------------------------------------
@analytics_bp.route('/admin/export', methods=['GET'])
@requires_role(['super_admin'])
def admin_export_data():
    """Export system data for CSV/PDF generation"""
    
    export_type = request.args.get('type', 'ideas')  # ideas, users, analytics
    
    if export_type == 'ideas':
        # Export all ideas
        ideas = list(ideas_coll.find(
            {"isDeleted": {"$ne": True}},
            {
                "_id": 1,
                "title": 1,
                "domain": 1,
                "subDomain": 1,
                "status": 1,
                "overallScore": 1,
                "innovatorName": 1,
                "mentorName": 1,
                "submittedAt": 1
            }
        ))
        
        # Convert to CSV-friendly format
        export_data = []
        for idea in ideas:
            export_data.append({
                "ID": idea.get('_id', ''),
                "Title": idea.get('title', ''),
                "Domain": idea.get('domain', ''),
                "Sub-Domain": idea.get('subDomain', ''),
                "Status": idea.get('status', ''),
                "Score": idea.get('overallScore', 0),
                "Innovator": idea.get('innovatorName', ''),
                "Mentor": idea.get('mentorName', ''),
                "Submitted": idea.get('submittedAt', '').isoformat() if idea.get('submittedAt') else ''
            })
        
        return jsonify({
            "success": True,
            "data": export_data,
            "count": len(export_data)
        }), 200
    
    return jsonify({"error": "Invalid export type"}), 400
