from flask import Blueprint, request, jsonify
from app.database.mongo import ideas_coll, users_coll, results_coll
from app.middleware.auth import requires_auth, requires_role
from app.utils.validators import clean_doc
from bson import ObjectId
from app.utils.validators import normalize_user_id, normalize_any_id_field, clean_doc, get_user_by_any_id
from app.utils.id_helpers import find_user, ids_match


analytics_bp = Blueprint('analytics', __name__, url_prefix='/api/analytics')

def get_innovator_ids_for_role(caller_id, caller_role):
    """
    Get innovator ObjectIds based on caller role.
    
    Data hierarchy:
    - College Admin (_id) 
      └─> TTCs (collegeId = admin._id as STRING)
          └─> Innovators (ttcCoordinatorId = ttc._id as STRING)
              └─> Ideas (innovatorId = innovator._id as ObjectId)
    """
    # Ensure caller_id is ObjectId
    if isinstance(caller_id, str):
        caller_id = ObjectId(caller_id)
    
    caller_id_str = str(caller_id)
    
    if caller_role == 'ttc_coordinator':
        # ✅ Direct: Get innovators with ttcCoordinatorId = this TTC's _id (as string)
        innovator_ids = users_coll.distinct("_id", {
            "ttcCoordinatorId": caller_id_str,  # Stored as STRING
            "role": {"$in": ["innovator", "individual_innovator"]},
            "isDeleted": {"$ne": True}
        })
        print(f"🔍 TTC {caller_id_str}: Found {len(innovator_ids)} innovators")
        return innovator_ids
    
    elif caller_role == 'college_admin':
        # ✅ Two-step: College Admin -> TTCs -> Innovators
        print(f"🔍 College Admin: {caller_id_str}")
        
        # Step 1: Find all TTCs in this college
        ttc_ids = users_coll.distinct("_id", {
            "collegeId": caller_id_str,  # Stored as STRING
            "role": "ttc_coordinator",
            "isDeleted": {"$ne": True}
        })
        
        print(f"  ├─ Found {len(ttc_ids)} TTCs")
        
        if not ttc_ids:
            return []
        
        # Step 2: Find all innovators under these TTCs
        ttc_ids_str = [str(tid) for tid in ttc_ids]
        innovator_ids = users_coll.distinct("_id", {
            "ttcCoordinatorId": {"$in": ttc_ids_str},  # STRING array
            "role": {"$in": ["innovator", "individual_innovator"]},
            "isDeleted": {"$ne": True}
        })
        
        print(f"  └─ Found {len(innovator_ids)} innovators")
        return innovator_ids
    
    elif caller_role == 'super_admin':
        # All innovators
        innovator_ids = users_coll.distinct("_id", {
            "role": {"$in": ["innovator", "individual_innovator"]},
            "isDeleted": {"$ne": True}
        })
        print(f"🔍 Super Admin: Found {len(innovator_ids)} total innovators")
        return innovator_ids
    
    else:
        return []

# -------------------------------------------------------------------------
# 1. DOMAIN TREND - Shows idea distribution by domain
# -------------------------------------------------------------------------
@analytics_bp.route('/domain-trend', methods=['GET'])
@requires_auth()
def domain_trend():
    """Domain-wise idea counts"""
    caller_id = request.user_id
    caller_role = request.user_role
    
    print(f"\n📊 Domain Trend: Role={caller_role}, ID={caller_id}")
    
    if caller_role in ['innovator', 'individual_innovator']:
        # Convert to ObjectId for innovator query
        if isinstance(caller_id, str):
            caller_id = ObjectId(caller_id)
        match_stage = {"innovatorId": caller_id, "isDeleted": {"$ne": True}}
    else:
        # Get innovators based on role hierarchy
        innovator_ids = get_innovator_ids_for_role(caller_id, caller_role)
        if not innovator_ids:
            print("⚠️ No innovators found")
            return jsonify({"success": True, "data": []}), 200
        
        # ✅ Use ObjectId array for innovatorId query
        match_stage = {
            "innovatorId": {"$in": innovator_ids},  # Already ObjectIds
            "isDeleted": {"$ne": True}
        }
    
    pipeline = [
        {"$match": match_stage},
        {"$group": {"_id": "$domain", "ideas": {"$sum": 1}}},
        {"$sort": {"ideas": -1}},
        {"$project": {"_id": 0, "name": "$_id", "ideas": 1}}
    ]
    
    data = list(ideas_coll.aggregate(pipeline))
    print(f"✅ Returning {len(data)} domains\n")
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

@analytics_bp.route('/idea-quality-trend', methods=['GET'])
@requires_role(['ttc_coordinator', 'college_admin', 'super_admin'])
def idea_quality_trend():
    """Monthly average scores"""
    caller_id = request.user_id
    caller_role = request.user_role
    
    innovator_ids = get_innovator_ids_for_role(caller_id, caller_role)
    if not innovator_ids:
        return jsonify({"success": True, "data": []}), 200
    
    pipeline = [
        {
            "$match": {
                "innovatorId": {"$in": innovator_ids},
                "isDeleted": {"$ne": True},
                "overallScore": {"$exists": True, "$ne": None}
            }
        },
        {
            "$addFields": {
                "month": {"$dateToString": {"format": "%b", "date": "$createdAt"}}
            }
        },
        {
            "$group": {
                "_id": "$month",
                "quality": {"$avg": "$overallScore"}
            }
        },
        {"$sort": {"_id": 1}}
    ]
    
    raw = list(ideas_coll.aggregate(pipeline))
    month_order = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    mapped = {m['_id']: round(m['quality'], 2) for m in raw}
    data = [{"month": m, "quality": mapped.get(m, 0)} for m in month_order]
    
    return jsonify({"success": True, "data": data}), 200

# =====================================================================
# 3. CATEGORY SUCCESS
# =====================================================================
@analytics_bp.route('/category-success', methods=['GET'])
@requires_role(['ttc_coordinator', 'college_admin', 'super_admin'])
def category_success():
    """Ideas by status per domain"""
    caller_id = request.user_id
    caller_role = request.user_role
    
    innovator_ids = get_innovator_ids_for_role(caller_id, caller_role)
    if not innovator_ids:
        return jsonify({"success": True, "data": []}), 200
    
    pipeline = [
        {"$match": {"innovatorId": {"$in": innovator_ids}, "isDeleted": {"$ne": True}}},
        {
            "$group": {
                "_id": "$domain",
                "approved": {"$sum": {"$cond": [{"$gte": ["$overallScore", 80]}, 1, 0]}},
                "moderate": {"$sum": {"$cond": [
                    {"$and": [{"$gte": ["$overallScore", 50]}, {"$lt": ["$overallScore", 80]}]},
                    1, 0
                ]}},
                "rejected": {"$sum": {"$cond": [{"$lt": ["$overallScore", 50]}, 1, 0]}}
            }
        },
        {"$project": {"_id": 0, "category": "$_id", "approved": 1, "moderate": 1, "rejected": 1}}
    ]
    
    data = list(ideas_coll.aggregate(pipeline))
    return jsonify({"success": True, "data": data}), 200

# =====================================================================
# 4. TOP INNOVATORS
# =====================================================================
@analytics_bp.route('/top-innovators', methods=['GET'])
@requires_role(['ttc_coordinator', 'college_admin', 'super_admin'])
def top_innovators():
    """Top 5 innovators by average score"""
    caller_id = request.user_id
    caller_role = request.user_role
    
    innovator_ids = get_innovator_ids_for_role(caller_id, caller_role)
    if not innovator_ids:
        return jsonify({"success": True, "data": []}), 200
    
    pipeline = [
        {
            "$match": {
                "innovatorId": {"$in": innovator_ids},
                "isDeleted": {"$ne": True},
                "overallScore": {"$exists": True, "$ne": None}
            }
        },
        {
            "$group": {
                "_id": "$innovatorId",
                "avgScore": {"$avg": "$overallScore"},
                "ideaCount": {"$sum": 1}
            }
        },
        {"$sort": {"avgScore": -1}},
        {"$limit": 5},
        {
            "$lookup": {
                "from": "users",
                "localField": "_id",
                "foreignField": "_id",
                "as": "user"
            }
        },
        {"$unwind": "$user"},
        {"$project": {"_id": 0, "name": "$user.name", "score": {"$round": ["$avgScore", 2]}}}
    ]
    
    data = list(ideas_coll.aggregate(pipeline))
    return jsonify({"success": True, "data": data}), 200

# =====================================================================
# 5. REJECTION REASONS
# =====================================================================
@analytics_bp.route('/rejection-reasons', methods=['GET'])
@requires_role(['ttc_coordinator', 'college_admin', 'super_admin'])
def rejection_reasons():
    """Top 4 rejection reasons"""
    caller_id = request.user_id
    caller_role = request.user_role
    
    innovator_ids = get_innovator_ids_for_role(caller_id, caller_role)
    if not innovator_ids:
        return jsonify({"success": True, "data": [{"name": "No data", "value": 1}]}), 200
    
    pipeline = [
        {
            "$match": {
                "innovatorId": {"$in": innovator_ids},
                "overallScore": {"$lt": 50},
                "isDeleted": {"$ne": True}
            }
        },
        {"$unwind": "$evaluatedData"},
        {"$match": {"evaluatedData.score": {"$lt": 50}}},
        {"$group": {"_id": "$evaluatedData.criterion", "value": {"$sum": 1}}},
        {"$sort": {"value": -1}},
        {"$limit": 4},
        {"$project": {"_id": 0, "name": "$_id", "value": 1, "fill": "hsl(var(--chart-3))"}}
    ]
    
    data = list(ideas_coll.aggregate(pipeline))
    if not data:
        data = [{"name": "No rejections", "value": 1, "fill": "hsl(var(--muted))"}]
    
    return jsonify({"success": True, "data": data}), 200

# =====================================================================
# 6. INNOVATOR ENGAGEMENT
# =====================================================================
@analytics_bp.route('/innovator-engagement', methods=['GET'])
@requires_role(['ttc_coordinator', 'college_admin', 'super_admin'])
def innovator_engagement():
    """Active vs inactive innovators"""
    caller_id = request.user_id
    caller_role = request.user_role
    
    innovator_ids = get_innovator_ids_for_role(caller_id, caller_role)
    if not innovator_ids:
        return jsonify({"success": True, "data": []}), 200
    
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

# -------------------------------------------------------------------------
# 8. INNOVATOR PERSONAL STATS - Overview metrics for innovator's dashboard
# -------------------------------------------------------------------------
@analytics_bp.route('/innovator/stats', methods=['GET'])
@requires_role(['innovator', 'individual_innovator'])
def innovator_personal_stats():
    """Personal stats for innovator"""
    caller_id = request.user_id
    
    if isinstance(caller_id, str):
        caller_id = ObjectId(caller_id)
    
    ideas = list(ideas_coll.find({
        "innovatorId": caller_id,
        "isDeleted": {"$ne": True}
    }))
    
    total_ideas = len(ideas)
    validated_ideas = [idea for idea in ideas if idea.get('overallScore') is not None]
    
    average_score = 0
    if validated_ideas:
        average_score = sum(idea['overallScore'] for idea in validated_ideas) / len(validated_ideas)
    
    approved_count = sum(1 for idea in validated_ideas if idea.get('overallScore', 0) >= 80)
    approval_rate = (approved_count / len(validated_ideas) * 100) if len(validated_ideas) > 0 else 0
    
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
# 10. INNOVATOR CLUSTER PERFORMANCE - Spider chart data
# -------------------------------------------------------------------------
@analytics_bp.route('/innovator/cluster-performance', methods=['GET'])
@requires_role(['innovator', 'individual_innovator'])
def innovator_cluster_performance():
    """Get average cluster scores for the innovator"""
    caller_id = request.user_id
    
    # Convert to both formats
    if isinstance(caller_id, str):
        try:
            caller_id_obj = ObjectId(caller_id)
        except:
            caller_id_obj = None
    else:
        caller_id_obj = caller_id
    
    caller_id_str = str(caller_id)
    
    print(f"📊 Fetching cluster performance for innovator: {caller_id_str}")
    
    # ✅ Query results_coll instead of ideas_coll
    from app.database.mongo import results_coll
    
    results = list(results_coll.find({
        "$or": [
            {"innovatorId": caller_id_obj},
            {"innovatorId": caller_id_str}
        ]
    }))
    
    print(f"   Found {len(results)} validation results")
    
    if not results:
        print("   No results found, returning default structure")
        return jsonify({
            "success": True,
            "data": {
                "Core Idea": 0,
                "Market Opportunity": 0,
                "Execution": 0,
                "Business Model": 0,
                "Team": 0,
                "Compliance": 0,
                "Risk & Strategy": 0
            }
        }), 200
    
    # ✅ FIX: cluster_scores is directly in validationResult, not nested
    cluster_totals = {}
    cluster_counts = {}
    
    for result in results:
        validation_result = result.get('validationResult', {})
        # ✅ Get cluster_scores directly from validationResult
        cluster_scores = validation_result.get('cluster_scores', {})
        
        print(f"   Result {result.get('_id')}: cluster_scores = {cluster_scores}")
        
        for cluster_name, score in cluster_scores.items():
            if score is not None:
                cluster_totals[cluster_name] = cluster_totals.get(cluster_name, 0) + score
                cluster_counts[cluster_name] = cluster_counts.get(cluster_name, 0) + 1
    
    print(f"   Cluster totals: {cluster_totals}")
    print(f"   Cluster counts: {cluster_counts}")
    
    # Calculate averages
    avg_cluster_scores = {}
    for cluster_name in cluster_totals:
        avg_cluster_scores[cluster_name] = round(
            cluster_totals[cluster_name] / cluster_counts[cluster_name],
            2
        )
    
    print(f"   Average cluster scores: {avg_cluster_scores}")
    
    return jsonify({
        "success": True,
        "data": avg_cluster_scores
    }), 200


@analytics_bp.route('/innovator/score-timeline', methods=['GET'])
@requires_role(['innovator', 'individual_innovator'])
def innovator_score_timeline():
    """Get score progression over time for the innovator"""
    caller_id = request.user_id
    
    # Convert to both formats
    if isinstance(caller_id, str):
        try:
            caller_id_obj = ObjectId(caller_id)
        except:
            caller_id_obj = None
    else:
        caller_id_obj = caller_id
    
    caller_id_str = str(caller_id)
    
    print(f"📈 Fetching score timeline for innovator: {caller_id_str}")
    
    from app.database.mongo import results_coll
    
    # ✅ Query with proper date field and sorting
    results = list(results_coll.find({
        "$or": [
            {"innovatorId": caller_id_obj},
            {"innovatorId": caller_id_str}
        ]
    }).sort("createdAt", 1))  # Use createdAt or check what date field exists
    
    print(f"   Found {len(results)} validation results")
    
    if not results:
        print("   No results found, returning empty array")
        return jsonify({
            "success": True,
            "data": []
        }), 200
    
    # Build timeline data
    timeline_data = []
    for result in results:
        validation_result = result.get('validationResult', {})
        overall_score = validation_result.get('overall_score')
        
        # ✅ Try multiple date fields
        date_submitted = result.get('submittedAt') or result.get('createdAt') or result.get('timestamp')
        title = result.get('title', 'Untitled Idea')
        
        print(f"   Checking result: title={title}, score={overall_score}, date={date_submitted}")
        
        if overall_score is not None and date_submitted:
            timeline_data.append({
                "date": date_submitted.isoformat() if hasattr(date_submitted, 'isoformat') else str(date_submitted),
                "score": round(overall_score, 2),
                "ideaTitle": title,
                "ideaId": str(result.get('ideaId', result.get('_id')))
            })
            print(f"   ✅ Added: {title} - Score: {overall_score}")
    
    print(f"   Timeline data points: {len(timeline_data)}")
    
    return jsonify({
        "success": True,
        "data": timeline_data
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
    """Compare TTCs in college"""
    caller_id = request.user_id
    
    if isinstance(caller_id, str):
        caller_id_str = str(ObjectId(caller_id))
    else:
        caller_id_str = str(caller_id)
    
    # Get all TTCs in this college
    ttcs = list(users_coll.find({
        "collegeId": caller_id_str,
        "role": "ttc_coordinator",
        "isDeleted": {"$ne": True}
    }, {"_id": 1, "name": 1}))
    
    if not ttcs:
        return jsonify({"success": True, "data": []}), 200
    
    performance_data = []
    for ttc in ttcs:
        ttc_id_str = str(ttc['_id'])
        
        # Get innovators under this TTC
        innovator_ids = users_coll.distinct("_id", {
            "ttcCoordinatorId": ttc_id_str,
            "role": {"$in": ["innovator", "individual_innovator"]},
            "isDeleted": {"$ne": True}
        })
        
        # Get ideas
        ideas = list(ideas_coll.find({
            "innovatorId": {"$in": innovator_ids},
            "isDeleted": {"$ne": True}
        }))
        
        total_ideas = len(ideas)
        approved_ideas = sum(1 for idea in ideas if idea.get('overallScore', 0) >= 80)
        approval_rate = (approved_ideas / total_ideas * 100) if total_ideas > 0 else 0
        
        performance_data.append({
            "ttcId": ttc_id_str,
            "name": ttc['name'],
            "ideas": total_ideas,
            "approved": approved_ideas,
            "approvalRate": round(approval_rate, 2)
        })
    
    performance_data.sort(key=lambda x: x['ideas'], reverse=True)
    return jsonify({"success": True, "data": performance_data}), 200

# -------------------------------------------------------------------------
# 13. COLLEGE SUMMARY STATS - Overview for college admin
# -------------------------------------------------------------------------
@analytics_bp.route('/college/summary', methods=['GET'])
@requires_role(['college_admin'])
def college_summary():
    """Summary for college admin"""
    caller_id = request.user_id
    
    if isinstance(caller_id, str):
        caller_id = ObjectId(caller_id)
    caller_id_str = str(caller_id)
    
    print(f"\n📊 College Summary for admin: {caller_id_str}")
    
    # Count TTCs in this college
    ttc_count = users_coll.count_documents({
        "collegeId": caller_id_str,  # STRING
        "role": "ttc_coordinator",
        "isDeleted": {"$ne": True}
    })
    print(f"  ├─ TTCs: {ttc_count}")
    
    # Get innovators via TTCs
    innovator_ids = get_innovator_ids_for_role(caller_id, 'college_admin')
    print(f"  ├─ Innovators: {len(innovator_ids)}")
    
    if not innovator_ids:
        return jsonify({
            "success": True,
            "data": {
                "totalTTCs": ttc_count,
                "totalInnovators": 0,
                "totalIdeas": 0,
                "approvedIdeas": 0,
                "approvalRate": 0
            }
        }), 200
    
    # Get ideas
    ideas = list(ideas_coll.find({
        "innovatorId": {"$in": innovator_ids},
        "isDeleted": {"$ne": True}
    }))
    print(f"  └─ Ideas: {len(ideas)}\n")
    
    total_ideas = len(ideas)
    approved_ideas = sum(1 for idea in ideas if idea.get('overallScore', 0) >= 80)
    approval_rate = (approved_ideas / total_ideas * 100) if total_ideas > 0 else 0
    
    return jsonify({
        "success": True,
        "data": {
            "totalTTCs": ttc_count,
            "totalInnovators": len(innovator_ids),
            "totalIdeas": total_ideas,
            "approvedIdeas": approved_ideas,
            "approvalRate": round(approval_rate, 2)
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
    """System-wide summary"""
    total_colleges = users_coll.count_documents({
        "role": "college_admin",
        "isDeleted": {"$ne": True}
    })
    
    total_ttcs = users_coll.count_documents({
        "role": "ttc_coordinator",
        "isDeleted": {"$ne": True}
    })
    
    total_innovators = users_coll.count_documents({
        "role": {"$in": ["innovator", "individual_innovator"]},
        "isDeleted": {"$ne": True}
    })
    
    total_ideas = ideas_coll.count_documents({"isDeleted": {"$ne": True}})
    
    ideas_with_scores = list(ideas_coll.find(
        {"overallScore": {"$exists": True, "$ne": None}, "isDeleted": {"$ne": True}},
        {"overallScore": 1}
    ))
    
    approved_ideas = sum(1 for idea in ideas_with_scores if idea.get('overallScore', 0) >= 80)
    approval_rate = (approved_ideas / total_ideas * 100) if total_ideas > 0 else 0
    avg_score = sum(idea.get('overallScore', 0) for idea in ideas_with_scores) / len(ideas_with_scores) if ideas_with_scores else 0
    
    return jsonify({
        "success": True,
        "data": {
            "totalColleges": total_colleges,
            "totalTTCs": total_ttcs,
            "totalInnovators": total_innovators,
            "totalIdeas": total_ideas,
            "approvedIdeas": approved_ideas,
            "approvalRate": round(approval_rate, 2),
            "avgScore": round(avg_score, 2)
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
