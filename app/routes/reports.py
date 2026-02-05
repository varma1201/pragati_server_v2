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
                if caller_user:
                    user_college_id = caller_user.get("collegeId")
                    idea_college_id = idea.get("collegeId")
                    ttc_id = idea.get("ttcCoordinatorId")
                    
                    print(f"🕵️ DEBUG: Checking College Admin Access")
                    print(f"   - Caller College: {user_college_id}")
                    print(f"   - Idea College: {idea_college_id}")
                    if ttc_id:
                        print(f"   - Found TTC ID on Idea: {ttc_id}")
                    else:
                        print("   - No TTC ID on Idea, checking innovator...")
                        innovator_id = idea.get("innovatorId")
                        if innovator_id:
                            innovator = find_user(innovator_id)
                            if innovator:
                                ttc_id = innovator.get("ttcCoordinatorId")
                                print(f"   - Found TTC ID via Innovator: {ttc_id}")

                                print(f"   - Found TTC ID via Innovator: {ttc_id}")


                    # Check direct college match
                    # LOGIC: The user IS the college (caller_id matches target collegeId)
                    if ids_match(caller_id, idea_college_id):
                        print(f"   ✅ MATCH: Caller ID {caller_id} matches Idea College ID")
                        authorized = True
                    
                    # Check via TTC coordinator
                    elif ttc_id:
                        ttc_user = find_user(ttc_id)
                        if ttc_user:
                            ttc_college_id = ttc_user.get("collegeId")
                            print(f"   - TTC User found. TTC College: {ttc_college_id}")
                            
                            if ids_match(caller_id, ttc_college_id):
                                print(f"   ✅ MATCH: Via TTC coordinator college match (Caller {caller_id} IS the college)")
                                authorized = True
                            else:
                                print(f"   ❌ MATCH FAILED: Caller {caller_id} != TTC college {ttc_college_id}")
                        else:
                            print(f"   ❌ TTC User not found for ID: {ttc_id}")
                    else:
                        print("   ❌ No direct connection and no TTC coordinator to check")
            
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
            authorized = False
            if caller_user:
                # Check direct college match
                # Check direct match (Caller IS the college)
                if ids_match(caller_id, idea.get("collegeId")):
                    authorized = True
                else:
                    # Check via TTC Coordinator (Idea or Innovator)
                    ttc_id = idea.get("ttcCoordinatorId")
                    if not ttc_id:
                         innovator = find_user(idea.get("innovatorId"))
                         if innovator:
                             ttc_id = innovator.get("ttcCoordinatorId")
                    
                    if ttc_id:
                        ttc_user = find_user(ttc_id)
                        if ttc_user:
                            ttc_college = ttc_user.get("collegeId")
                            # Check if Caller IS the college of the TTC
                            if ids_match(caller_id, ttc_college):
                                authorized = True
            
            if not authorized:
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
    
    Data model reality:
    - ideas.collegeId = null (NOT SET!)
    - ideas.ttcCoordinatorId = STRING (TTC who manages the innovator)
    - ideas.innovatorId = ObjectId
    """
    print("\n" + "=" * 80)
    print(f"🔧 build_role_based_query()")
    print("=" * 80)
    print(f"  caller_id: {caller_id} (type: {type(caller_id)})")
    print(f"  caller_role: {caller_role}")
    print(f"  data_source: {data_source}")
    
    base_query = {"isDeleted": {"$ne": True}}
    caller_id_str = str(caller_id)
    
    # ✅ INNOVATOR: See only their own ideas (innovatorId is ObjectId)
    if caller_role == "innovator" or caller_role == "individual_innovator":
        base_query.update(normalize_any_id_field("innovatorId", caller_id))
        print(f"  ✅ INNOVATOR: Filter by innovatorId = {caller_id}")
    
    # ✅ TTC COORDINATOR: See all ideas with ttcCoordinatorId = caller_id (STRING)
    elif caller_role == "ttc_coordinator":
        base_query["ttcCoordinatorId"] = caller_id_str
        print(f"  ✅ TTC: Filter by ttcCoordinatorId = '{caller_id_str}'")
    
    # ✅ COLLEGE ADMIN: Need to find TTCs first, then get their ideas
    elif caller_role == "college_admin":
        print(f"  🔧 COLLEGE ADMIN: Finding TTCs for college {caller_id_str}")
        
        # Step 1: Find all TTCs in this college
        ttc_ids = users_coll.distinct("_id", {
            "collegeId": caller_id_str,  # TTCs have collegeId
            "role": "ttc_coordinator",
            "isDeleted": {"$ne": True}
        })
        
        print(f"     ├─ Found {len(ttc_ids)} TTCs")
        
        if ttc_ids:
            # Step 2: Get ideas from these TTCs
            ttc_ids_str = [str(tid) for tid in ttc_ids]
            base_query["ttcCoordinatorId"] = {"$in": ttc_ids_str}
            print(f"     └─ Filter by ttcCoordinatorId in {ttc_ids_str}")
        else:
            # No TTCs found = no ideas
            print(f"     └─ ⚠️ No TTCs found - returning empty result set")
            base_query["_id"] = {"$in": []}
    
    # ✅ EXTERNAL MENTOR: See ideas where they are consultation mentor
    elif caller_role == "mentor":
        base_query.update(normalize_any_id_field("consultationMentorId", caller_id))
        print(f"  ✅ MENTOR: Filter by consultationMentorId = {caller_id}")
    
    # ✅ INTERNAL MENTOR: See ideas where they are assigned mentor
    elif caller_role == "internal_mentor":
        base_query.update(normalize_any_id_field("mentorId", caller_id))
        print(f"  ✅ INTERNAL MENTOR: Filter by mentorId = {caller_id}")
    
    # ✅ SUPER ADMIN: See everything
    elif caller_role == "super_admin":
        print(f"  ✅ SUPER ADMIN: No filters (all data)")
        pass
    
    else:
        print(f"  ❌ UNKNOWN ROLE: {caller_role} - returning empty result set")
        base_query["_id"] = {"$in": []}
    
    # ========================================
    # APPLY DATA SOURCE SPECIFIC FILTERS
    # ========================================
    print(f"\n  📊 Data source: {data_source}")
    
    if data_source == "consultations":
        print(f"  🔧 Adding consultation filters...")
        if caller_role == "mentor":
            print(f"    ✓ Mentor: Already filtered by consultationMentorId")
            pass
        elif caller_role == "internal_mentor":
            base_query["mentorId"] = {"$exists": True, "$ne": None}
            print(f"    ✓ Internal Mentor: Added mentorId existence check")
        else:
            base_query["consultationMentorId"] = {"$exists": True, "$ne": None}
            print(f"    ✓ Other roles: Added consultationMentorId existence check")
    
    elif data_source == "validated_ideas":
        print(f"  🔧 Adding validated ideas filter...")
        base_query["overallScore"] = {"$exists": True, "$ne": None}
        print(f"    ✓ Added overallScore existence check")
    
    print(f"\n  📋 Final query: {base_query}")
    print("=" * 80)
    
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
    print("=" * 80)
    print("📊 IDEAS SUMMARY EXPORT STARTED")
    print("=" * 80)
    
    try:
        caller_id = request.user_id
        caller_role = request.user_role
        
        print(f"👤 Caller ID: {caller_id} (type: {type(caller_id)})")
        print(f"👤 Caller Role: {caller_role}")
        
        logger.info(f"📊 Ideas summary requested by {caller_role}: {caller_id}")
        
        # Build role-based query
        print("\n🔧 Building role-based query...")
        query = build_role_based_query(caller_id, caller_role, "ideas")
        
        # Optional filters
        domain_filter = request.args.get("domain")
        stage_filter = request.args.get("stage")
        
        print(f"🎯 Domain filter: {domain_filter}")
        print(f"🎯 Stage filter: {stage_filter}")
        
        if domain_filter:
            query["domain"] = domain_filter
        
        if stage_filter:
            query["stage"] = stage_filter
        
        # ✅ ADD: Debug logging
        print(f"\n🔍 Final Query: {query}")
        logger.info(f"🔍 Query: {query}")
        
        # Fetch ideas
        print("\n🔎 Fetching ideas from database...")
        ideas = list(ideas_coll.find(query).sort("submittedAt", -1))
        
        print(f"✅ Found {len(ideas)} ideas for export")
        logger.info(f"✅ Found {len(ideas)} ideas for export")
        
        if len(ideas) == 0:
            print("⚠️ No ideas found - returning 404")
            print("=" * 80)
            return jsonify({
                "error": "No data available",
                "message": f"No ideas found for {caller_role}. Query: {query}"
            }), 404
        
        # Show sample of ideas found
        print(f"\n📋 Sample of ideas found:")
        for i, idea in enumerate(ideas[:3], 1):
            print(f"  {i}. {idea.get('title', 'Untitled')} (ID: {idea.get('_id')})")
            print(f"     - Innovator: {idea.get('innovatorId')}")
            print(f"     - TTC: {idea.get('ttcCoordinatorId')}")
            print(f"     - College: {idea.get('collegeId')}")
        
        # Generate CSV
        print("\n📝 Generating CSV...")
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header row
        writer.writerow([
            "Idea ID", "Title", "Innovator Name", "Innovator Email",
            "Domain", "Subdomain", "TRL", "Overall Score", "Stage",
            "Submitted Date", "Mentor", "TTC ID", "College ID"
        ])
        
        # Data rows
        rows_written = 0
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
                str(idea.get("ttcCoordinatorId", "")),
                str(idea.get("collegeId", ""))
            ])
            rows_written += 1
        
        print(f"✅ Wrote {rows_written} rows to CSV")
        
        # Save record in generated_reports collection
        print("\n💾 Saving report record to database...")
        report_doc = {
            "userId": caller_id,
            "name": f"Ideas Summary - {datetime.now().strftime('%Y-%m-%d')}",
            "type": "CSV",
            "status": "Ready",
            "recordCount": len(ideas),
            "createdAt": datetime.now(timezone.utc),
            "isDeleted": False
        }
        result = generated_reports_coll.insert_one(report_doc)
        print(f"✅ Report record saved with ID: {result.inserted_id}")
        
        # Convert to bytes
        print("\n📦 Converting to downloadable file...")
        output.seek(0)
        bytes_output = io.BytesIO()
        bytes_output.write(output.getvalue().encode('utf-8-sig'))
        bytes_output.seek(0)
        
        filename = f"ideas_summary_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
        
        print(f"✅ Generated CSV: {filename}")
        print(f"📁 File size: {len(bytes_output.getvalue())} bytes")
        logger.info(f"✅ Generated CSV: {filename}")
        
        print("=" * 80)
        print("✅ IDEAS SUMMARY EXPORT COMPLETED SUCCESSFULLY")
        print("=" * 80)
        
        return send_file(
            bytes_output,
            mimetype='text/csv',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        print("=" * 80)
        print(f"❌ ERROR in export_ideas_summary: {type(e).__name__}")
        print(f"❌ Message: {str(e)}")
        print("=" * 80)
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
    print("=" * 80)
    print("📊 CONSULTATIONS EXPORT STARTED")
    print("=" * 80)
    
    try:
        caller_id = request.user_id
        caller_role = request.user_role
        
        print(f"👤 Caller ID: {caller_id} (type: {type(caller_id)})")
        print(f"👤 Caller Role: {caller_role}")
        
        logger.info(f"📊 Consultation export requested by {caller_role}: {caller_id}")
        
        print("\n🔧 Building role-based query for consultations...")
        query = build_role_based_query(caller_id, caller_role, "consultations")
        
        print(f"🔍 Final Query: {query}")
        
        print("\n🔎 Fetching consultations from database...")
        consultations = list(ideas_coll.find(query).sort("consultationScheduledAt", -1))
        
        print(f"✅ Found {len(consultations)} consultations")
        logger.info(f"✅ Found {len(consultations)} consultations")
        
        if len(consultations) == 0:
            print("⚠️ No consultations found - returning 404")
            print("=" * 80)
            return jsonify({
                "error": "No consultations found",
                "message": f"No consultation data available for {caller_role}. Query: {query}"
            }), 404
        
        # Show sample of consultations found
        print(f"\n📋 Sample of consultations found:")
        for i, idea in enumerate(consultations[:3], 1):
            print(f"  {i}. {idea.get('title', 'Untitled')} (ID: {idea.get('_id')})")
            print(f"     - Mentor: {idea.get('consultationMentorId')}")
            print(f"     - Status: {idea.get('consultationStatus', 'N/A')}")
            print(f"     - Scheduled: {idea.get('consultationScheduledAt')}")
        
        # Generate CSV
        print("\n📝 Generating CSV...")
        output = io.StringIO()
        writer = csv.writer(output)
        
        writer.writerow([
            "Idea ID", "Idea Title", "Innovator", "Innovator Email",
            "Consultant Mentor", "Mentor Email", "Status", 
            "Scheduled Date", "Consultation Notes"
        ])
        
        rows_written = 0
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
            rows_written += 1
        
        print(f"✅ Wrote {rows_written} rows to CSV")
        
        # Save record
        print("\n💾 Saving report record to database...")
        report_doc = {
            "userId": caller_id,
            "name": f"Consultations - {datetime.now().strftime('%Y-%m-%d')}",
            "type": "CSV",
            "status": "Ready",
            "recordCount": len(consultations),
            "createdAt": datetime.now(timezone.utc),
            "isDeleted": False
        }
        result = generated_reports_coll.insert_one(report_doc)
        print(f"✅ Report record saved with ID: {result.inserted_id}")
        
        print("\n📦 Converting to downloadable file...")
        output.seek(0)
        bytes_output = io.BytesIO()
        bytes_output.write(output.getvalue().encode('utf-8-sig'))
        bytes_output.seek(0)
        
        filename = f"consultations_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
        
        print(f"✅ Generated CSV: {filename}")
        print(f"📁 File size: {len(bytes_output.getvalue())} bytes")
        
        print("=" * 80)
        print("✅ CONSULTATIONS EXPORT COMPLETED SUCCESSFULLY")
        print("=" * 80)
        
        return send_file(
            bytes_output,
            mimetype='text/csv',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        print("=" * 80)
        print(f"❌ ERROR in export_consultations: {type(e).__name__}")
        print(f"❌ Message: {str(e)}")
        print("=" * 80)
        logger.error(f"❌ Failed to generate consultations report: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@reports_bp.route("/hub/custom/generate", methods=["POST"])
@requires_auth()
def generate_custom_report():
    """
    Generate custom report (Reports Hub).
    """
    print("=" * 80)
    print("📊 CUSTOM REPORT GENERATION STARTED")
    print("=" * 80)
    
    try:
        caller_id = request.user_id
        caller_role = request.user_role
        body = request.get_json()
        
        print(f"👤 Caller ID: {caller_id} (type: {type(caller_id)})")
        print(f"👤 Caller Role: {caller_role}")
        print(f"📦 Request Body: {body}")
        
        logger.info(f"📊 Custom report requested by {caller_role}: {caller_id}")
        
        report_name = body.get("reportName", f"Custom Report {datetime.now().strftime('%Y%m%d')}")
        format_type = body.get("format", "csv").lower()
        data_source = body.get("dataSource", "ideas")
        date_range = body.get("dateRange", {})
        filters = body.get("filters", {})
        columns = body.get("columns", [])
        schedule = body.get("schedule")
        
        print(f"\n📋 Report Configuration:")
        print(f"   Report Name: {report_name}")
        print(f"   Format: {format_type}")
        print(f"   Data Source: {data_source}")
        print(f"   Date Range: {date_range}")
        print(f"   Filters: {filters}")
        print(f"   Columns: {columns}")
        print(f"   Schedule: {schedule}")
        
        # Build query
        print(f"\n🔧 Building role-based query...")
        query = build_role_based_query(caller_id, caller_role, data_source)
        print(f"🔍 Initial query: {query}")
        
        # Apply date range
        if date_range.get("from") or date_range.get("to"):
            print(f"\n📅 Applying date range filter...")
            date_filter = {}
            
            if date_range.get("from"):
                try:
                    from_date = datetime.fromisoformat(date_range["from"].replace('Z', '+00:00'))
                    date_filter["$gte"] = from_date
                    print(f"   ✅ From date: {from_date}")
                except Exception as e:
                    print(f"   ⚠️ Failed to parse 'from' date: {e}")
                    pass
            
            if date_range.get("to"):
                try:
                    to_date = datetime.fromisoformat(date_range["to"].replace('Z', '+00:00'))
                    date_filter["$lte"] = to_date
                    print(f"   ✅ To date: {to_date}")
                except Exception as e:
                    print(f"   ⚠️ Failed to parse 'to' date: {e}")
                    pass
            
            if date_filter:
                query["submittedAt"] = date_filter
                print(f"   ✅ Date filter applied: {date_filter}")
        else:
            print(f"\n📅 No date range filter provided")
        
        # Apply filters
        if filters:
            print(f"\n🎯 Applying custom filters...")
            for key, value in filters.items():
                if value and value != "all":
                    query[key] = value
                    print(f"   ✅ {key} = {value}")
                else:
                    print(f"   ⏭️  Skipped {key} (value: {value})")
        else:
            print(f"\n🎯 No custom filters provided")
        
        print(f"\n🔍 Final Query: {query}")
        
        # Handle scheduling
        if schedule and schedule.get("type") == "scheduled":
            print(f"\n⏰ Scheduling report for future execution...")
            
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
            
            result = scheduled_reports_coll.insert_one(scheduled_doc)
            print(f"✅ Scheduled report saved with ID: {result.inserted_id}")
            
            report_id = f"REP-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            print(f"✅ Report ID: {report_id}")
            print("=" * 80)
            
            return jsonify({
                "success": True,
                "message": f"Report '{report_name}' scheduled successfully",
                "reportId": report_id
            }), 200
        
        # Generate immediately
        print(f"\n⚡ Generating report immediately...")
        print(f"   Format: {format_type}")
        
        if format_type == "csv":
            print(f"   ✅ Calling _generate_csv_custom()...")
            return _generate_csv_custom(query, columns, report_name, data_source, caller_id)
        else:
            print(f"   ❌ Invalid format: {format_type}")
            print("=" * 80)
            return jsonify({"error": f"Invalid format '{format_type}'. Use 'csv'"}), 400
        
    except Exception as e:
        print("=" * 80)
        print(f"❌ ERROR in generate_custom_report: {type(e).__name__}")
        print(f"❌ Message: {str(e)}")
        print("=" * 80)
        logger.error(f"❌ Custom report generation failed: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


def _generate_csv_custom(query, columns, report_name, data_source, user_id):
    """Helper to generate CSV from custom query"""
    print("\n" + "=" * 80)
    print("📝 _generate_csv_custom() STARTED")
    print("=" * 80)
    
    try:
        print(f"📊 Parameters:")
        print(f"   Query: {query}")
        print(f"   Columns: {columns}")
        print(f"   Report Name: {report_name}")
        print(f"   Data Source: {data_source}")
        print(f"   User ID: {user_id}")
        
        # Fetch data
        print(f"\n🔎 Fetching data from {data_source} collection...")
        data = list(ideas_coll.find(query).sort("createdAt", -1))
        
        print(f"✅ Found {len(data)} records")
        
        if not data:
            print(f"⚠️ No data found - returning 404")
            print("=" * 80)
            return jsonify({
                "error": "No data found",
                "message": "No records match your filter criteria.",
                "query": query
            }), 404
        
        # Show sample of data found
        print(f"\n📋 Sample of data found:")
        for i, item in enumerate(data[:3], 1):
            print(f"  {i}. {item.get('title', 'Untitled')} (ID: {item.get('_id')})")
            print(f"     - Domain: {item.get('domain')}")
            print(f"     - Score: {item.get('overallScore', 'N/A')}")
        
        logger.info(f"✅ Found {len(data)} records for custom report")
        
        # Column mapping
        print(f"\n🗂️  Setting up column mapping...")
        column_map = {
            "ID": lambda x: str(x.get("_id")),
            "Title": lambda x: x.get("title", ""),
            "Innovator Name": lambda x: find_user(x.get("innovatorId")).get("name", "") if find_user(x.get("innovatorId")) else "",
            "Innovator Email": lambda x: find_user(x.get("innovatorId")).get("email", "") if find_user(x.get("innovatorId")) else "",
            "Domain": lambda x: x.get("domain", ""),
            "Subdomain": lambda x: x.get("subDomain", ""),
            "Score": lambda x: x.get("overallScore", "N/A"),
            "Stage": lambda x: x.get("stage", ""),
            "Status": lambda x: x.get("status", ""),
            "TRL": lambda x: x.get("trl", ""),
            "Date": lambda x: x.get("submittedAt").strftime("%Y-%m-%d") if x.get("submittedAt") else "",
            "TTC ID": lambda x: x.get("ttcCoordinatorId", ""),
            "College ID": lambda x: x.get("collegeId", "")
        }
        
        # If no columns specified, use all
        if not columns:
            columns = list(column_map.keys())
            print(f"   ℹ️  No columns specified - using all: {columns}")
        else:
            print(f"   ✅ Using specified columns: {columns}")
        
        # Generate CSV
        print(f"\n📝 Generating CSV...")
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header row
        writer.writerow(columns)
        print(f"   ✅ Header row written: {columns}")
        
        # Data rows
        rows_written = 0
        for item in data:
            row = [column_map.get(col, lambda x: "")(item) for col in columns]
            writer.writerow(row)
            rows_written += 1
        
        print(f"   ✅ Wrote {rows_written} data rows")
        
        # Save record
        print(f"\n💾 Saving report record to database...")
        report_doc = {
            "userId": user_id,
            "name": report_name,
            "type": "CSV",
            "status": "Ready",
            "recordCount": len(data),
            "createdAt": datetime.now(timezone.utc),
            "isDeleted": False
        }
        result = generated_reports_coll.insert_one(report_doc)
        print(f"✅ Report record saved with ID: {result.inserted_id}")
        
        # Convert to bytes
        print(f"\n📦 Converting to downloadable file...")
        output.seek(0)
        bytes_output = io.BytesIO()
        bytes_output.write(output.getvalue().encode('utf-8-sig'))
        bytes_output.seek(0)
        
        filename = f"{report_name.replace(' ', '_')}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
        
        print(f"✅ Generated CSV: {filename}")
        print(f"📁 File size: {len(bytes_output.getvalue())} bytes")
        print("=" * 80)
        print("✅ CSV GENERATION COMPLETED SUCCESSFULLY")
        print("=" * 80)
        
        return send_file(
            bytes_output,
            mimetype='text/csv',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        print("=" * 80)
        print(f"❌ ERROR in _generate_csv_custom: {type(e).__name__}")
        print(f"❌ Message: {str(e)}")
        print("=" * 80)
        logger.error(f"❌ CSV generation failed: {e}")
        import traceback
        traceback.print_exc()
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
