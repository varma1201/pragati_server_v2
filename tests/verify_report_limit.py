
import os
import sys
from datetime import datetime, timezone, timedelta

# Ensure 'app' module can be found
sys.path.append(os.getcwd())

from app.database.mongo import generated_reports_coll

def test_report_limit():
    print("🧪 Starting Report Limit Verification...")
    
    # Mock Data
    college_id = "test_college_admin_limit_check"
    
    now = datetime.now(timezone.utc)
    start_of_month = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    
    # 1. Clear existing test logs
    generated_reports_coll.delete_many({"collegeId": college_id})
    
    # 2. Insert 10 distinct reports for this month
    reports = []
    for i in range(10):
        reports.append({
            "userId": "user_1",
            "collegeId": college_id,
            "ideaId": f"idea_{i}", # Distinct IDs
            "reportName": f"Report {i}",
            "type": "PDF",
            "status": "Generated",
            "createdAt": now
        })
    
    generated_reports_coll.insert_many(reports)
    print(f"📝 Inserted count: {len(reports)} reports")
    
    # 3. Validation Logic (from reports_pdf.py)
    pipeline = [
        {
            "$match": {
                "collegeId": college_id,
                "type": "PDF",
                "createdAt": {"$gte": start_of_month}
            }
        },
        {
            "$group": {
                "_id": "$ideaId"
            }
        },
        {
            "$count": "distinct_ideas"
        }
    ]
    
    count_res = list(generated_reports_coll.aggregate(pipeline))
    current_count = count_res[0]["distinct_ideas"] if count_res else 0
    
    print(f"📊 Current Count: {current_count}")
    
    if current_count != 10:
        print(f"❌ Verification Failed: Expected 10, got {current_count}")
        sys.exit(1)
        
    print("✅ Verification Passed: Count is correctly 10")
    
    # 4. Cleanup
    generated_reports_coll.delete_many({"collegeId": college_id})
    print("🧹 Cleanup done")

if __name__ == "__main__":
    test_report_limit()
