from flask import Blueprint, request, jsonify, current_app
from app.middleware.auth import requires_auth
from app.database.mongo import results_coll  # ✅ Add this collection
from app.utils.validators import clean_doc, parse_oid
from bson import ObjectId
from datetime import datetime

reports_bp = Blueprint("reports", __name__, url_prefix="/api/reports")

# =========================================================================
# GET REPORT BY ID - Retrieve full detailed analysis
# =========================================================================

@reports_bp.route("/<report_id>", methods=["GET"])  # ✅ FIXED: Proper route parameter
@requires_auth
def get_report_data(report_id):
    """Get specific report data by ID (full detailed analysis)"""
    try:
        # ✅ Validate & convert ID
        try:
            if isinstance(report_id, str):
                oid = ObjectId(report_id)
            else:
                oid = report_id
        except Exception as e:
            return jsonify({"error": "Invalid report id"}), 400

        # ✅ Read from Mongo 'results' collection
        report = results_coll.find_one({"_id": oid})

        if not report:
            return jsonify({"error": "Report not found"}), 404

        return jsonify({
            "success": True,
            "data": clean_doc(report)
        }), 200

    except Exception as e:
        current_app.logger.exception(f"Failed to get report {report_id}")
        return jsonify({
            "error": "Failed to retrieve report",
            "details": str(e)
        }), 500
