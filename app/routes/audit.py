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
def get_audit_trail_raw():
    """
    Get audit trail logs - NO DECORATORS for debugging
    """
    print("\n" + "🎯" * 40)
    print("✅ [AUDIT TRAIL] ROUTE HANDLER ENTERED!!!")
    print(f"✅ Method: {request.method}")
    print(f"✅ Path: {request.path}")
    print(f"✅ Args: {dict(request.args)}")
    print("🎯" * 40 + "\n")
    
    try:
        # Manual auth check
        auth_header = request.headers.get('Authorization')
        print(f"🔐 Authorization header: {auth_header[:50] if auth_header else 'NONE'}...")
        
        if not auth_header:
            print("❌ No auth header")
            return jsonify({"error": "Missing authorization"}), 401
        
        # Decode token manually
        try:
            from app.services.auth_service import AuthService
            from flask import current_app
            
            token = auth_header.replace('Bearer ', '').strip()
            auth_service = AuthService(current_app.config['JWT_SECRET'])
            payload = auth_service.decode_token(token)
            
            caller_id = payload.get('uid')
            caller_role = payload.get('role')
            
            print(f"✅ Token decoded:")
            print(f"   User ID: {caller_id}")
            print(f"   User Role: {caller_role}")
            
        except Exception as e:
            print(f"❌ Token decode failed: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"error": "Invalid token"}), 401
        
        # Check role
        allowed_roles = ["college_admin", "principal", "college_principal", "admin", "super_admin"]
        print(f"🔍 Role check: '{caller_role}' in {allowed_roles} = {caller_role in allowed_roles}")
        
        if caller_role not in allowed_roles:
            print(f"❌ Role denied: {caller_role}")
            return jsonify({
                "error": "Access denied",
                "yourRole": caller_role,
                "allowedRoles": allowed_roles
            }), 403
        
        print(f"✅ Role authorized: {caller_role}")
        
        # Convert caller_id to ObjectId
        if isinstance(caller_id, str):
            caller_id_obj = ObjectId(caller_id)
        else:
            caller_id_obj = caller_id
        
        # Pagination
        page = int(request.args.get("page", 1))
        limit = int(request.args.get("limit", 50))
        skip = (page - 1) * limit
        
        print(f"📄 Pagination: page={page}, limit={limit}, skip={skip}")
        
        # Build query
        query = {}
        
        # Role-based filtering
        admin_roles = ["college_admin", "principal", "college_principal", "admin"]
        
        if caller_role in admin_roles:
            print(f"🏛️ College admin filtering...")
            
            # 🔧 FIX: Filter by college admin's _id (which IS the college identifier)
            # The collegeId in audit logs should match the college admin's _id
            college_id_str = str(caller_id_obj)
            
            query["collegeId"] = college_id_str
            print(f"✅ Filtering audit logs where collegeId = {college_id_str}")
            
        elif caller_role == "super_admin":
            print(f"✅ Super admin - no filtering")
        
        # Category filter
        category = request.args.get("category")
        if category and category != "all":
            query["category"] = category
            print(f"🏷️ Category filter: {category}")
        
        # Search filter
        search = request.args.get("search")
        if search:
            query["$or"] = [
                {"actor": {"$regex": search, "$options": "i"}},
                {"action": {"$regex": search, "$options": "i"}},
                {"actorEmail": {"$regex": search, "$options": "i"}}
            ]
            print(f"🔍 Search filter: {search}")
        
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
                print(f"📅 Date filter: {date_filter}")
        
        print(f"\n📊 Final MongoDB query: {query}\n")
        
        # Get total count
        total = audit_logs_coll.count_documents(query)
        print(f"📊 Total matching logs: {total}")
        
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
                "targetId": str(log.get("targetId")) if log.get("targetId") else None,
                "targetType": log.get("targetType"),
                "metadata": log.get("metadata", {})
            })
        
        print(f"✅ Returning {len(logs)} logs")
        print("🎯" * 40 + "\n")
        
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
        
    except Exception as e:
        print(f"\n❌ EXCEPTION in get_audit_trail:")
        print(f"   Type: {type(e).__name__}")
        print(f"   Message: {str(e)}")
        import traceback
        traceback.print_exc()
        print("\n")
        
        return jsonify({"error": str(e)}), 500


@audit_bp.route("/stats", methods=["GET"])
def get_audit_stats():
    """Get audit trail statistics"""
    try:
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
        allowed_roles = ["college_admin", "principal", "college_principal", "admin", "super_admin"]
        if caller_role not in allowed_roles:
            return jsonify({"error": "Access denied"}), 403
        
        # Build base query
        base_query = {}
        
        admin_roles = ["college_admin", "principal", "college_principal", "admin"]
        if caller_role in admin_roles:
            # 🔧 Filter by college admin's _id
            base_query["collegeId"] = str(caller_id)
        
        # Total logs
        total_logs = audit_logs_coll.count_documents(base_query)
        
        # Logs by category
        category_pipeline = [
            {"$match": base_query},
            {"$group": {
                "_id": "$category",
                "count": {"$sum": 1}
            }}
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
                "userId": str(item["_id"]),
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
        
    except Exception as e:
        logger.error(f"Failed to fetch audit stats: {e}")
        return jsonify({"error": str(e)}), 500


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

