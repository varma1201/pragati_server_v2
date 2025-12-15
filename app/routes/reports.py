"""
Reports Module - TWO SEPARATE SYSTEMS

1. Idea Validation Reports (Individual idea analysis)
   - GET /api/reports/idea/<idea_id> - Get validation report for one idea
   - POST /api/reports/idea/<idea_id>/pdf - Generate PDF for one idea

2. Reports Hub (Bulk exports & analytics)
   - GET /api/reports/hub/list - List generated reports
   - GET /api/reports/hub/standard/ideas-summary - CSV of all ideas
   - POST /api/reports/hub/custom/generate - Custom report builder
   - POST /api/reports/hub/ai/summarize - AI-powered summary
"""

from flask import Blueprint, request, jsonify, current_app, send_file
from app.middleware.auth import requires_auth, requires_role
from app.database.mongo import (
    ideas_coll, users_coll, results_coll, 
    generated_reports_coll, scheduled_reports_coll
)
from app.utils.validators import clean_doc, parse_oid, normalize_any_id_field
from app.utils.id_helpers import find_user, ids_match
from datetime import datetime, timezone, timedelta
from bson import ObjectId
import csv
import io
import logging

reports_bp = Blueprint("reports", __name__, url_prefix="/api/reports")
logger = logging.getLogger(__name__)

# =========================================================================
# SYSTEM 1: IDEA VALIDATION REPORTS report get 
# =========================================================================
@reports_bp.route("/<idea_id>", methods=["GET"])
@requires_auth()
def get_report_by_idea_id(idea_id):
    """
    Get validation report from RESULTS collection by idea ID.
    Route: GET /api/reports/{ideaId}
    
    Flow:
    1. Receive idea_id
    2. Search results_coll where ideaId matches
    3. Return full result document
    """
    try:
        # Convert idea_id to ObjectId
        try:
            idea_oid = ObjectId(idea_id) if isinstance(idea_id, str) else idea_id
        except Exception as e:
            logger.error(f"❌ Invalid idea ID: {idea_id}")
            return jsonify({"error": "Invalid idea ID format"}), 400
        
        logger.info(f"📊 Fetching report from results_coll for ideaId: {idea_id}")
        
        # ========================================
        # SEARCH RESULTS COLLECTION BY ideaId
        # ========================================
        result_doc = results_coll.find_one({"ideaId": idea_id})
        
        if not result_doc:
            logger.warning(f"⚠️ No result found for ideaId: {idea_id}")
            return jsonify({
                "success": False,
                "error": "Report not found",
                "message": f"No validation result found for idea {idea_id}"
            }), 404
        
        logger.info(f"✅ Result found in results_coll for ideaId: {idea_id}")
        
        # ========================================
        # AUTHORIZATION CHECK (Optional)
        # ========================================
        # Get the idea to check permissions
        idea = ideas_coll.find_one({"_id": idea_oid, "isDeleted": {"$ne": True}})
        
        if idea:
            caller_id = request.user_id
            caller_role = request.user_role
            authorized = False
            
            if caller_role in ["innovator", "individual_innovator"]:
                if ids_match(idea.get("innovatorId"), caller_id):
                    authorized = True
                else:
                    caller_user = find_user(caller_id)
                    if caller_user:
                        user_email = caller_user.get("email")
                        if user_email and user_email in idea.get("invitedTeam", []):
                            authorized = True
            
            elif caller_role == "ttc_coordinator":
                innovator_ids = users_coll.distinct("_id", {
                    **normalize_any_id_field("ttcCoordinatorId", caller_id),
                    "role": {"$in": ["innovator", "individual_innovator"]},
                    "isDeleted": {"$ne": True}
                })
                if any(ids_match(idea.get("innovatorId"), uid) for uid in innovator_ids):
                    authorized = True
            
            elif caller_role == "college_admin":
                caller_user = find_user(caller_id)
                if caller_user and ids_match(caller_user.get("collegeId"), idea.get("collegeId")):
                    authorized = True
            
            elif caller_role == "mentor":
                if ids_match(idea.get("consultationMentorId"), caller_id):
                    authorized = True
            
            elif caller_role == "internal_mentor":
                if ids_match(idea.get("mentorId"), caller_id):
                    authorized = True
            
            elif caller_role == "super_admin":
                authorized = True
            
            if not authorized:
                logger.error(f"❌ Access denied for {caller_role} ({caller_id}) to idea {idea_id}")
                return jsonify({"error": "Access denied"}), 403
            
            logger.info(f"✅ Authorization passed for {caller_role}")
        
        # ========================================
        # RETURN FULL RESULT DOCUMENT
        # ========================================
        # Clean the document (convert ObjectIds to strings, remove sensitive fields)
        result_data = clean_doc(result_doc)
        
        logger.info(f"✅ Returning full result document for ideaId: {idea_id}")
        
        return jsonify({
            "success": True,
            "data": result_data
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Failed to get report for idea {idea_id}: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "error": "Failed to retrieve report",
            "message": str(e)
        }), 500

# =========================================================================
# SYSTEM 1: IDEA VALIDATION REPORTS (Individual idea analysis)
# =========================================================================

@reports_bp.route("/idea/<idea_id>", methods=["GET"])
@requires_auth()
def get_idea_report(idea_id):
    """
    Get AI validation report for a specific idea.
    This is the ORIGINAL report system - one report per idea.
    
    Returns:
    {
        "success": true,
        "data": {
            "ideaId": "...",
            "overallScore": 85,
            "clusterScores": {...},
            "recommendations": [...],
            "createdAt": "..."
        }
    }
    """
    try:
        # Validate & convert ID
        try:
            if isinstance(idea_id, str):
                oid = ObjectId(idea_id)
            else:
                oid = idea_id
        except Exception as e:
            return jsonify({"error": "Invalid idea ID"}), 400
        
        # Check if idea exists and user has access
        idea = ideas_coll.find_one({"_id": oid, "isDeleted": {"$ne": True}})
        if not idea:
            return jsonify({"error": "Idea not found"}), 404
        
        caller_id = request.user_id
        caller_role = request.user_role
        
        # Authorization check
        if caller_role == "innovator":
            if not ids_match(idea.get("innovatorId"), caller_id):
                return jsonify({"error": "Access denied"}), 403
        elif caller_role == "ttc_coordinator":
            innovator_ids = users_coll.distinct("_id", {
                **normalize_any_id_field("ttcCoordinatorId", caller_id),
                "role": "innovator"
            })
            if not any(ids_match(idea.get("innovatorId"), uid) for uid in innovator_ids):
                return jsonify({"error": "Access denied"}), 403
        elif caller_role == "college_admin":
            caller_user = find_user(caller_id)
            if not caller_user or not ids_match(caller_user.get("collegeId"), idea.get("collegeId")):
                return jsonify({"error": "Access denied"}), 403
        
        # Read from 'results' collection (validation report)
        report = results_coll.find_one({"ideaId": oid})
        
        if not report:
            # Return idea data even if report not generated yet
            return jsonify({
                "success": True,
                "data": {
                    "ideaId": str(oid),
                    "title": idea.get("title"),
                    "overallScore": idea.get("overallScore"),
                    "clusterScores": idea.get("clusterScores", {}),
                    "status": "Report not yet generated",
                    "reportGenerated": False
                }
            }), 200
        
        return jsonify({
            "success": True,
            "data": clean_doc(report)
        }), 200
        
    except Exception as e:
        current_app.logger.exception(f"Failed to get idea report {idea_id}")
        return jsonify({
            "error": "Failed to retrieve report",
            "details": str(e)
        }), 500


@reports_bp.route("/idea/<idea_id>/pdf", methods=["GET"])
@requires_auth()
def download_idea_report_pdf(idea_id):
    """
    Generate and download PDF report for a specific idea.
    Delegates to reports_pdf.py logic.
    """
    try:
        # TODO: Integrate with existing reports_pdf.py
        return jsonify({
            "error": "PDF generation not yet implemented",
            "message": "Use the existing PDF endpoint"
        }), 501
        
    except Exception as e:
        logger.error(f"PDF generation failed: {e}")
        return jsonify({"error": str(e)}), 500


# =========================================================================
# SYSTEM 2: REPORTS HUB (Bulk exports & analytics)
# =========================================================================

def build_role_based_query(caller_id, caller_role, data_source="ideas"):
    """
    Build MongoDB query based on user role for Reports Hub.
    """
    base_query = {"isDeleted": {"$ne": True}}
    
    if caller_role == "innovator" or caller_role == "individual_innovator":
        base_query.update(normalize_any_id_field("innovatorId", caller_id))
    
    elif caller_role == "ttc_coordinator":
        innovator_ids = users_coll.distinct("_id", {
            **normalize_any_id_field("ttcCoordinatorId", caller_id),
            "role": {"$in": ["innovator", "individual_innovator"]},
            "isDeleted": {"$ne": True}
        })
        base_query["innovatorId"] = {"$in": innovator_ids}
    
    elif caller_role == "college_admin":
        caller_user = find_user(caller_id)
        if caller_user and caller_user.get("collegeId"):
            college_id = caller_user["collegeId"]
            innovator_ids = users_coll.distinct("_id", {
                **normalize_any_id_field("collegeId", college_id),
                "role": {"$in": ["innovator", "individual_innovator"]},
                "isDeleted": {"$ne": True}
            })
            base_query["innovatorId"] = {"$in": innovator_ids}
        else:
            base_query["innovatorId"] = {"$in": []}
    
    # ✅ NEW: Add mentor support (external mentor)
    elif caller_role == "mentor":
        # Mentors see ideas where they are assigned as consultationMentorId
        base_query.update(normalize_any_id_field("consultationMentorId", caller_id))
    
    # ✅ NEW: Add internal_mentor support
    elif caller_role == "internal_mentor":
        # Internal mentors see ideas where they are assigned as mentorId
        base_query.update(normalize_any_id_field("mentorId", caller_id))
    
    elif caller_role == "super_admin":
        pass  # See everything
    
    else:
        raise ValueError(f"Unknown role: {caller_role}")
    
    # Data source filters
    if data_source == "consultations":
        # ✅ UPDATED: Different field for external vs internal mentors
        if caller_role == "mentor":
            # Already filtered by consultationMentorId above
            pass
        elif caller_role == "internal_mentor":
            base_query["mentorId"] = {"$exists": True, "$ne": None}
        else:
            base_query["consultationMentorId"] = {"$exists": True, "$ne": None}
    
    elif data_source == "validated_ideas":
        base_query["overallScore"] = {"$exists": True, "$ne": None}
    
    return base_query


@reports_bp.route("/hub/list", methods=["GET"])
@requires_auth()
def list_generated_reports():
    """
    Get list of generated reports for Reports Hub.
    This is SEPARATE from idea validation reports.
    """
    print("list_generated_reports")
    try:
        caller_id = request.user_id
        page = int(request.args.get("page", 1))
        limit = int(request.args.get("limit", 20))
        skip = (page - 1) * limit
        
        # Query generated_reports collection
        query = {"userId": caller_id, "isDeleted": {"$ne": True}}
        
        total = generated_reports_coll.count_documents(query)
        cursor = generated_reports_coll.find(query).sort("createdAt", -1).skip(skip).limit(limit)
        
        reports = []
        for doc in cursor:
            reports.append({
                "id": str(doc.get("_id")),
                "name": doc.get("name"),
                "type": doc.get("type"),
                "date": doc.get("createdAt").strftime("%Y-%m-%d") if doc.get("createdAt") else "",
                "status": doc.get("status", "Ready")
            })
        
        return jsonify({
            "success": True,
            "data": reports,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Failed to list reports: {e}")
        return jsonify({"error": str(e)}), 500


@reports_bp.route("/hub/standard/ideas-summary", methods=["GET"])
@requires_auth()
def export_ideas_summary():
    """
    CSV export of all ideas (Reports Hub - bulk export).
    DIFFERENT from individual idea reports.
    """
    try:
        caller_id = request.user_id
        caller_role = request.user_role
        
        logger.info(f"📊 Ideas summary requested by {caller_role}: {caller_id}")
        
        # Build role-based query
        query = build_role_based_query(caller_id, caller_role, "ideas")
        
        # Optional filters
        if request.args.get("domain"):
            query["domain"] = request.args.get("domain")
        if request.args.get("stage"):
            query["stage"] = request.args.get("stage")
        
        # Fetch ideas
        ideas = list(ideas_coll.find(query).sort("submittedAt", -1))
        logger.info(f"✅ Found {len(ideas)} ideas for export")
        
        if len(ideas) == 0:
            return jsonify({
                "error": "No data available",
                "message": "No ideas found for your role."
            }), 404
        
        # Generate CSV
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header row
        writer.writerow([
            "Idea ID", "Title", "Innovator Name", "Innovator Email",
            "Domain", "Subdomain", "TRL", "Overall Score", "Stage", 
            "Submitted Date", "Mentor", "College ID"
        ])
        
        # Data rows
        for idea in ideas:
            innovator = find_user(idea.get("innovatorId"))
            mentor = find_user(idea.get("mentorId")) if idea.get("mentorId") else None
            
            writer.writerow([
                str(idea.get("_id")),
                idea.get("title", ""),
                innovator.get("name", "") if innovator else "",
                innovator.get("email", "") if innovator else "",
                idea.get("domain", ""),
                idea.get("subDomain", ""),
                idea.get("trl", ""),
                idea.get("overallScore", "N/A"),
                idea.get("stage", ""),
                idea.get("submittedAt").strftime("%Y-%m-%d %H:%M") if idea.get("submittedAt") else "",
                mentor.get("name", "") if mentor else "",
                idea.get("collegeId", "")
            ])
        
        # Save record in generated_reports collection
        report_doc = {
            "userId": caller_id,
            "name": f"Ideas Summary - {datetime.now().strftime('%Y-%m-%d')}",
            "type": "CSV",
            "status": "Ready",
            "recordCount": len(ideas),
            "createdAt": datetime.now(timezone.utc),
            "isDeleted": False
        }
        generated_reports_coll.insert_one(report_doc)
        
        # Convert to bytes
        output.seek(0)
        bytes_output = io.BytesIO()
        bytes_output.write(output.getvalue().encode('utf-8-sig'))
        bytes_output.seek(0)
        
        filename = f"ideas_summary_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
        
        logger.info(f"✅ Generated CSV: {filename}")
        
        return send_file(
            bytes_output,
            mimetype='text/csv',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        logger.error(f"❌ Failed to generate ideas summary: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@reports_bp.route("/hub/standard/consultations", methods=["GET"])
@requires_auth()
def export_consultations():
    """
    CSV export of consultation history (Reports Hub).
    """
    try:
        caller_id = request.user_id
        caller_role = request.user_role
        
        logger.info(f"📊 Consultation export requested by {caller_role}: {caller_id}")
        
        query = build_role_based_query(caller_id, caller_role, "consultations")
        
        consultations = list(ideas_coll.find(query).sort("consultationScheduledAt", -1))
        logger.info(f"✅ Found {len(consultations)} consultations")
        
        if len(consultations) == 0:
            return jsonify({
                "error": "No consultations found",
                "message": "No consultation data available for your role."
            }), 404
        
        # Generate CSV
        output = io.StringIO()
        writer = csv.writer(output)
        
        writer.writerow([
            "Idea ID", "Idea Title", "Innovator", "Innovator Email",
            "Consultant Mentor", "Mentor Email", "Status", 
            "Scheduled Date", "Consultation Notes"
        ])
        
        for idea in consultations:
            innovator = find_user(idea.get("innovatorId"))
            mentor = find_user(idea.get("consultationMentorId"))
            
            writer.writerow([
                str(idea.get("_id")),
                idea.get("title", ""),
                innovator.get("name", "") if innovator else "",
                innovator.get("email", "") if innovator else "",
                mentor.get("name", "") if mentor else "Unassigned",
                mentor.get("email", "") if mentor else "",
                idea.get("consultationStatus", "assigned"),
                idea.get("consultationScheduledAt").strftime("%Y-%m-%d %H:%M") if idea.get("consultationScheduledAt") else "Not scheduled",
                idea.get("consultationNotes", "")
            ])
        
        # Save record
        report_doc = {
            "userId": caller_id,
            "name": f"Consultations - {datetime.now().strftime('%Y-%m-%d')}",
            "type": "CSV",
            "status": "Ready",
            "recordCount": len(consultations),
            "createdAt": datetime.now(timezone.utc),
            "isDeleted": False
        }
        generated_reports_coll.insert_one(report_doc)
        
        output.seek(0)
        bytes_output = io.BytesIO()
        bytes_output.write(output.getvalue().encode('utf-8-sig'))
        bytes_output.seek(0)
        
        filename = f"consultations_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
        
        return send_file(
            bytes_output,
            mimetype='text/csv',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        logger.error(f"❌ Failed to generate consultations report: {e}")
        return jsonify({"error": str(e)}), 500


@reports_bp.route("/hub/custom/generate", methods=["POST"])
@requires_auth()
def generate_custom_report():
    """
    Generate custom report (Reports Hub).
    """
    try:
        caller_id = request.user_id
        caller_role = request.user_role
        body = request.get_json()
        
        logger.info(f"📊 Custom report requested by {caller_role}: {caller_id}")
        
        report_name = body.get("reportName", f"Custom Report {datetime.now().strftime('%Y%m%d')}")
        format_type = body.get("format", "csv").lower()
        data_source = body.get("dataSource", "ideas")
        date_range = body.get("dateRange", {})
        filters = body.get("filters", {})
        columns = body.get("columns", [])
        schedule = body.get("schedule")
        
        # Build query
        query = build_role_based_query(caller_id, caller_role, data_source)
        
        # Apply date range
        if date_range.get("from") or date_range.get("to"):
            date_filter = {}
            if date_range.get("from"):
                try:
                    date_filter["$gte"] = datetime.fromisoformat(date_range["from"].replace('Z', '+00:00'))
                except:
                    pass
            if date_range.get("to"):
                try:
                    date_filter["$lte"] = datetime.fromisoformat(date_range["to"].replace('Z', '+00:00'))
                except:
                    pass
            if date_filter:
                query["submittedAt"] = date_filter
        
        # Apply filters
        for key, value in filters.items():
            if value and value != "all":
                query[key] = value
        
        # Handle scheduling
        if schedule and schedule.get("type") == "scheduled":
            scheduled_doc = {
                "userId": caller_id,
                "reportName": report_name,
                "format": format_type,
                "dataSource": data_source,
                "query": query,
                "columns": columns,
                "schedule": schedule,
                "status": "scheduled",
                "createdAt": datetime.now(timezone.utc),
                "nextRunAt": datetime.now(timezone.utc) + timedelta(days=1)  # TODO: Calculate properly
            }
            scheduled_reports_coll.insert_one(scheduled_doc)
            
            return jsonify({
                "success": True,
                "message": f"Report '{report_name}' scheduled successfully",
                "reportId": f"REP-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            }), 200
        
        # Generate immediately
        if format_type == "csv":
            return _generate_csv_custom(query, columns, report_name, data_source, caller_id)
        else:
            return jsonify({"error": "Invalid format. Use 'csv'"}), 400
        
    except Exception as e:
        logger.error(f"❌ Custom report generation failed: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


def _generate_csv_custom(query, columns, report_name, data_source, user_id):
    """Helper to generate CSV from custom query"""
    try:
        data = list(ideas_coll.find(query).sort("createdAt", -1))
        
        if not data:
            return jsonify({
                "error": "No data found",
                "message": "No records match your filter criteria."
            }), 404
        
        logger.info(f"✅ Found {len(data)} records for custom report")
        
        # Column mapping
        column_map = {
            "ID": lambda x: str(x.get("_id")),
            "Title": lambda x: x.get("title", ""),
            "Innovator Name": lambda x: find_user(x.get("innovatorId")).get("name", "") if find_user(x.get("innovatorId")) else "",
            "Domain": lambda x: x.get("domain", ""),
            "Score": lambda x: x.get("overallScore", "N/A"),
            "Stage": lambda x: x.get("stage", ""),
            "Date": lambda x: x.get("submittedAt").strftime("%Y-%m-%d") if x.get("submittedAt") else ""
        }
        
        if not columns:
            columns = list(column_map.keys())
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(columns)
        
        for item in data:
            row = [column_map.get(col, lambda x: "")(item) for col in columns]
            writer.writerow(row)
        
        # Save record
        report_doc = {
            "userId": user_id,
            "name": report_name,
            "type": "CSV",
            "status": "Ready",
            "recordCount": len(data),
            "createdAt": datetime.now(timezone.utc),
            "isDeleted": False
        }
        generated_reports_coll.insert_one(report_doc)
        
        output.seek(0)
        bytes_output = io.BytesIO()
        bytes_output.write(output.getvalue().encode('utf-8-sig'))
        bytes_output.seek(0)
        
        filename = f"{report_name.replace(' ', '_')}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
        
        return send_file(
            bytes_output,
            mimetype='text/csv',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        logger.error(f"❌ CSV generation failed: {e}")
        raise


@reports_bp.route("/hub/ai/summarize", methods=["POST"])
@requires_auth()
def generate_ai_summary():
    """
    Generate AI-powered summary (Reports Hub).
    """
    try:
        caller_id = request.user_id
        caller_role = request.user_role
        body = request.get_json()
        
        query_text = body.get("query", "Summarize the validation data")
        data_scope = body.get("dataScope", "ideas")
        
        logger.info(f"🤖 AI summary requested: {query_text}")
        
        mongo_query = build_role_based_query(caller_id, caller_role, data_scope)
        
        ideas = list(ideas_coll.find(mongo_query).sort("overallScore", -1).limit(50))
        
        if not ideas:
            return jsonify({
                "error": "No data available",
                "message": "No ideas found for your role to generate a summary."
            }), 404
        
        # Generate summary (TODO: Integrate OpenAI)
        summary = _generate_fallback_summary(ideas, query_text, caller_role)
        
        # Save report
        report_id = f"REP-AI-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        report_doc = {
            "_id": report_id,
            "userId": caller_id,
            "name": f"AI Summary - {datetime.now().strftime('%Y-%m-%d')}",
            "type": "AI",
            "summary": summary,
            "query": query_text,
            "recordCount": len(ideas),
            "createdAt": datetime.now(timezone.utc),
            "status": "Ready",
            "isDeleted": False
        }
        generated_reports_coll.insert_one(report_doc)
        
        return jsonify({
            "success": True,
            "summary": summary,
            "reportId": report_id,
            "generatedReport": {
                "id": report_id,
                "name": report_doc["name"],
                "type": "AI",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "status": "Ready"
            }
        }), 200
        
    except Exception as e:
        logger.error(f"❌ AI summary failed: {e}")
        return jsonify({"error": str(e)}), 500


def _generate_fallback_summary(ideas, user_query, role):
    """Generate basic summary without OpenAI"""
    total = len(ideas)
    avg_score = sum(idea.get("overallScore", 0) for idea in ideas if idea.get("overallScore")) / total if total > 0 else 0
    
    domains = {}
    for idea in ideas:
        domain = idea.get("domain", "Unknown")
        domains[domain] = domains.get(domain, 0) + 1
    
    top_domains = sorted(domains.items(), key=lambda x: x[1], reverse=True)[:3]
    high_performers = [idea for idea in ideas if idea.get("overallScore", 0) >= 80]
    
    summary = f"""# Validation Data Summary

**Generated for**: {role.replace('_', ' ').title()}  
**Query**: "{user_query}"  
**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}

---

## 📊 Overview

- **Total Ideas Analyzed**: {total}
- **Average Validation Score**: {avg_score:.1f}/100
- **High Performers (≥80)**: {len(high_performers)} ideas
- **Needs Improvement (<60)**: {sum(1 for idea in ideas if idea.get("overallScore", 0) < 60)} ideas

## 🎯 Domain Distribution

"""
    
    for domain, count in top_domains:
        summary += f"- **{domain}**: {count} ideas ({count/total*100:.1f}%)\n"
    
    summary += "\n## ⭐ Top 5 Ideas\n\n"
    
    for i, idea in enumerate(sorted(ideas, key=lambda x: x.get("overallScore", 0), reverse=True)[:5], 1):
        summary += f"{i}. **{idea.get('title', 'Untitled')}** - Score: {idea.get('overallScore', 'N/A')}/100\n"
        summary += f"   - Domain: {idea.get('domain', 'N/A')}\n"
        summary += f"   - Stage: {idea.get('stage', 'N/A')}\n\n"
    
    summary += """## 💡 Recommendations

1. **Focus on High Performers**: Prioritize resources for ideas scoring above 80
2. **Domain Concentration**: Consider diversifying or deepening focus based on distribution
3. **Mentoring Support**: Provide additional guidance for ideas scoring below 60
4. **Cross-domain Collaboration**: Explore partnerships across different domains

---

*Note: This is a basic summary. For AI-powered insights, configure OpenAI API key.*
"""
    
    return summary


@reports_bp.route("/hub/<report_id>", methods=["DELETE"])
@requires_auth()
def delete_hub_report(report_id):
    """Soft delete a Reports Hub report"""
    try:
        caller_id = request.user_id
        
        result = generated_reports_coll.update_one(
            {"_id": report_id, "userId": caller_id},
            {"$set": {"isDeleted": True, "deletedAt": datetime.now(timezone.utc)}}
        )
        
        if result.matched_count == 0:
            return jsonify({"error": "Report not found or access denied"}), 404
        
        return jsonify({
            "success": True,
            "message": "Report deleted successfully"
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Failed to delete report: {e}")
        return jsonify({"error": str(e)}), 500

@reports_bp.route("/hub/<report_id>/download", methods=["GET"])
@requires_auth()
def download_generated_report(report_id):
    """
    Download a previously generated report from Reports Hub
    """
    try:
        caller_id = request.user_id
        
        # Find the report
        report = generated_reports_coll.find_one({
            "_id": report_id,
            "userId": caller_id,
            "isDeleted": {"$ne": True}
        })
        
        if not report:
            return jsonify({"error": "Report not found or access denied"}), 404
        
        if report.get("status") != "Ready":
            return jsonify({"error": "Report is not ready for download"}), 400
        
        # Check if report has stored file path or needs regeneration
        if report.get("filePath"):
            # If file is stored in S3 or local storage
            return send_file(
                report["filePath"],
                as_attachment=True,
                download_name=report.get("fileName", "report.csv")
            )
        else:
            # Report needs to be regenerated
            # Re-run the query and generate file
            report_type = report.get("type", "CSV")
            
            if report_type == "CSV":
                # Regenerate CSV from stored query
                query = report.get("query", {})
                columns = report.get("columns", [])
                data_source = report.get("dataSource", "ideas")
                
                return _generate_csv_custom(
                    query, 
                    columns, 
                    report.get("name"), 
                    data_source, 
                    caller_id
                )
            else:
                return jsonify({"error": "Unsupported report type"}), 400
                
    except Exception as e:
        logger.error(f"❌ Failed to download report: {e}")
        return jsonify({"error": str(e)}), 500
