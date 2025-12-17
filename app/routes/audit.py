"""
Audit Trail API - FULL DEBUG VERSION
"""

from flask import Blueprint, request, jsonify
from app.middleware.auth import requires_auth, requires_role
from app.database.mongo import audit_logs_coll, users_coll
from app.utils.validators import clean_doc, normalize_any_id_field
from app.utils.id_helpers import find_user
from datetime import datetime, timezone, timedelta
from bson import ObjectId
import logging

audit_bp = Blueprint("audit", __name__, url_prefix="/api/audit")
logger = logging.getLogger(__name__)

print("\n" + "🎯" * 40)
print("📦 [AUDIT MODULE] audit_bp Blueprint registered")
print(f"📦 Blueprint name: {audit_bp.name}")
print(f"📦 URL prefix: {audit_bp.url_prefix}")
print("🎯" * 40 + "\n")


@audit_bp.before_request
def before_audit_request():
    """Log every request to audit endpoints"""
    print("\n" + "🌐" * 40)
    print(f"📥 [AUDIT BEFORE_REQUEST] {request.method} {request.path}")
    print(f"📥 Full URL: {request.url}")
    print(f"📥 Endpoint: {request.endpoint}")
    print(f"📥 Has Authorization: {bool(request.headers.get('Authorization'))}")
    print("🌐" * 40 + "\n")


@audit_bp.route("/trail", methods=["GET"])
@requires_role(['college_admin', 'ttc_coordinator', 'super_admin'])
def get_audit_trail():
    """
    Get audit trail logs with proper role-based filtering.
    """
    caller_id = request.user_id
    caller_role = request.user_role
    
    # Convert to ObjectId
    if isinstance(caller_id, str):
        caller_id_obj = ObjectId(caller_id)
    else:
        caller_id_obj = caller_id
    caller_id_str = str(caller_id_obj)
    
    print(f"\n📊 Audit Trail Request:")
    print(f"  Role: {caller_role}")
    print(f"  User ID: {caller_id_str}")
    
    # Pagination
    page = int(request.args.get("page", 1))
    limit = int(request.args.get("limit", 50))
    skip = (page - 1) * limit
    
    # Build query
    query = {}
    
    # ✅ Role-based filtering
    if caller_role == "college_admin":
        # College admin sees logs for their college
        # Their _id IS the collegeId
        query["collegeId"] = caller_id_str
        print(f"  Filter: collegeId = {caller_id_str}")
        
    elif caller_role == "ttc_coordinator":
        # TTC sees logs from their college
        # Get their collegeId first
        ttc = users_coll.find_one({"_id": caller_id_obj}, {"collegeId": 1})
        if ttc and ttc.get("collegeId"):
            query["collegeId"] = ttc["collegeId"]
            print(f"  Filter: collegeId = {ttc['collegeId']}")
        else:
            # No college assigned, return empty
            print(f"  No college assigned to TTC")
            return jsonify({
                "success": True,
                "data": [],
                "pagination": {"page": page, "limit": limit, "total": 0, "pages": 0}
            }), 200
            
    elif caller_role == "super_admin":
        # Super admin sees all logs
        print(f"  Filter: None (super admin)")
    
    else:
        # Other roles not allowed
        return jsonify({"error": "Access denied"}), 403
    
    # Category filter
    category = request.args.get("category")
    if category and category != "all":
        query["category"] = category
    
    # Search filter
    search = request.args.get("search")
    if search:
        query["$or"] = [
            {"actor": {"$regex": search, "$options": "i"}},
            {"action": {"$regex": search, "$options": "i"}},
            {"actorEmail": {"$regex": search, "$options": "i"}}
        ]
    
    # Date range filter
    start_date = request.args.get("startDate")
    end_date = request.args.get("endDate")
    if start_date or end_date:
        date_filter = {}
        if start_date:
            try:
                date_filter["$gte"] = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            except:
                pass
        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                date_filter["$lt"] = end_dt + timedelta(days=1)
            except:
                pass
        if date_filter:
            query["timestamp"] = date_filter
    
    print(f"  Final Query: {query}\n")
    
    # Get total count
    total = audit_logs_coll.count_documents(query)
    print(f"  Total matching: {total}")
    
    # Fetch logs
    cursor = audit_logs_coll.find(query).sort("timestamp", -1).skip(skip).limit(limit)
    
    logs = []
    for log in cursor:
        logs.append({
            "id": str(log.get("_id")),
            "logId": log.get("logId"),
            "timestamp": log.get("timestamp").isoformat() if log.get("timestamp") else "",
            "actor": log.get("actor"),
            "actorEmail": log.get("actorEmail"),
            "actorRole": log.get("actorRole"),
            "action": log.get("action"),
            "category": log.get("category"),
            "targetId": log.get("targetId"),
            "targetType": log.get("targetType"),
            "metadata": log.get("metadata", {})
        })
    
    return jsonify({
        "success": True,
        "data": logs,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit
        }
    }), 200


@audit_bp.route("/stats", methods=["GET"])
@requires_role(['college_admin', 'ttc_coordinator', 'super_admin'])
def get_audit_stats():
    """Get audit trail statistics"""
    caller_id = request.user_id
    caller_role = request.user_role
    
    # Convert to ObjectId
    if isinstance(caller_id, str):
        caller_id_obj = ObjectId(caller_id)
    else:
        caller_id_obj = caller_id
    caller_id_str = str(caller_id_obj)
    
    # Build base query
    base_query = {}
    
    if caller_role == "college_admin":
        base_query["collegeId"] = caller_id_str
    elif caller_role == "ttc_coordinator":
        ttc = users_coll.find_one({"_id": caller_id_obj}, {"collegeId": 1})
        if ttc and ttc.get("collegeId"):
            base_query["collegeId"] = ttc["collegeId"]
        else:
            return jsonify({
                "success": True,
                "data": {"totalLogs": 0, "byCategory": {}, "recentActivityCount": 0, "mostActiveUsers": []}
            }), 200
    # super_admin: no filter
    
    # Total logs
    total_logs = audit_logs_coll.count_documents(base_query)
    
    # Logs by category
    category_pipeline = [
        {"$match": base_query},
        {"$group": {"_id": "$category", "count": {"$sum": 1}}}
    ]
    category_results = list(audit_logs_coll.aggregate(category_pipeline))
    by_category = {item["_id"]: item["count"] for item in category_results}
    
    # Recent activity (last 7 days)
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    recent_query = {**base_query, "timestamp": {"$gte": seven_days_ago}}
    recent_count = audit_logs_coll.count_documents(recent_query)
    
    # Most active users
    active_users_pipeline = [
        {"$match": base_query},
        {"$group": {
            "_id": "$actorId",
            "actor": {"$first": "$actor"},
            "actorRole": {"$first": "$actorRole"},
            "actionCount": {"$sum": 1}
        }},
        {"$sort": {"actionCount": -1}},
        {"$limit": 5}
    ]
    active_users_results = list(audit_logs_coll.aggregate(active_users_pipeline))
    most_active_users = [
        {
            "userId": item["_id"],
            "name": item["actor"],
            "role": item["actorRole"],
            "actionCount": item["actionCount"]
        }
        for item in active_users_results
    ]
    
    return jsonify({
        "success": True,
        "data": {
            "totalLogs": total_logs,
            "byCategory": by_category,
            "recentActivityCount": recent_count,
            "mostActiveUsers": most_active_users
        }
    }), 200


@audit_bp.route("/export", methods=["GET"])
def export_audit_trail():
    """Export audit trail as CSV"""
    try:
        from flask import send_file
        import csv
        import io
        
        # Manual auth
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({"error": "Missing authorization"}), 401
        
        from app.services.auth_service import AuthService
        from flask import current_app
        
        token = auth_header.replace('Bearer ', '').strip()
        auth_service = AuthService(current_app.config['JWT_SECRET'])
        payload = auth_service.decode_token(token)
        
        caller_id = payload.get('uid')
        caller_role = payload.get('role')
        
        # Convert to ObjectId
        if isinstance(caller_id, str):
            caller_id = ObjectId(caller_id)
        
        # Check role
        allowed_roles = ["college_admin"]
        if caller_role not in allowed_roles:
            return jsonify({"error": "Access denied"}), 403
        
        # Build query
        query = {}
        
        admin_roles = ["college_admin"]
        if caller_role in admin_roles:
            # 🔧 Filter by college admin's _id
            query["collegeId"] = str(caller_id)
        
        # Apply filters
        category = request.args.get("category")
        if category and category != "all":
            query["category"] = category
        
        search = request.args.get("search")
        if search:
            query["$or"] = [
                {"actor": {"$regex": search, "$options": "i"}},
                {"action": {"$regex": search, "$options": "i"}}
            ]
        
        # Fetch all matching logs (no pagination for export)
        cursor = audit_logs_coll.find(query).sort("timestamp", -1).limit(1000)
        
        # Generate CSV
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow([
            "Log ID", "Timestamp", "Actor", "Actor Email", "Actor Role",
            "Action", "Category", "Target Type", "Target ID"
        ])
        
        # Data rows
        for log in cursor:
            writer.writerow([
                log.get("logId", ""),
                log.get("timestamp").strftime("%Y-%m-%d %H:%M:%S") if log.get("timestamp") else "",
                log.get("actor", ""),
                log.get("actorEmail", ""),
                log.get("actorRole", ""),
                log.get("action", ""),
                log.get("category", ""),
                log.get("targetType", ""),
                str(log.get("targetId", "")) if log.get("targetId") else ""
            ])
        
        # Convert to bytes
        output.seek(0)
        bytes_output = io.BytesIO()
        bytes_output.write(output.getvalue().encode('utf-8-sig'))
        bytes_output.seek(0)
        
        filename = f"audit_trail_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        return send_file(
            bytes_output,
            mimetype='text/csv',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        logger.error(f"Failed to export audit trail: {e}")
        return jsonify({"error": str(e)}), 500


@audit_bp.route("/test", methods=["GET"])
def test_route():
    """Simple test route to verify blueprint is working"""
    print("✅ TEST ROUTE HIT!")
    return jsonify({"message": "Audit blueprint is working!"}), 200

