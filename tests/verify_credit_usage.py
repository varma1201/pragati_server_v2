
import os
import sys
from datetime import datetime, timezone, timedelta

# Ensure 'app' module can be found
sys.path.append(os.getcwd())

from app.database.mongo import audit_logs_coll
from app.services.audit_service import AuditService

def test_credit_aggregation():
    print("🧪 Starting Credit Usage Verification...")
    
    # Mock Actor ID
    college_id = "test_college_admin_verify_script"
    
    now = datetime.now(timezone.utc)
    start_of_month = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    last_month = start_of_month - timedelta(days=5)
    
    # 1. Clear existing test logs
    audit_logs_coll.delete_many({"actorId": college_id})
    
    # 2. Insert mock logs
    logs = [
        # ✅ Should be counted (Today)
        {
            "actorId": college_id,
            "category": AuditService.CATEGORY_CREDIT,
            "action": "Approved 10 credits",
            "metadata": {"amount": 10},
            "createdAt": now,
            "collegeId": college_id
        },
        # ✅ Should be counted (Start of month)
        {
            "actorId": college_id,
            "category": AuditService.CATEGORY_CREDIT,
            "action": "Approved 5 credits",
            "metadata": {"amount": 5},
            "createdAt": start_of_month,
            "collegeId": college_id
        },
        # ❌ Should NOT be counted (Last month)
        {
            "actorId": college_id,
            "category": AuditService.CATEGORY_CREDIT,
            "action": "Approved 100 credits",
            "metadata": {"amount": 100},
            "createdAt": last_month,
            "collegeId": college_id
        },
        # ❌ Should NOT be counted (Wrong Action - "Requested")
        {
            "actorId": college_id,
            "category": AuditService.CATEGORY_CREDIT,
            "action": "Requested 50 credits",
            "metadata": {"amount": 50},
            "createdAt": now,
            "collegeId": college_id
        },
        # ❌ Should NOT be counted (Wrong Category)
        {
            "actorId": college_id,
            "category": AuditService.CATEGORY_USER_MGMT,
            "action": "Approved user",
            "metadata": {"amount": 10}, # Irrelevant metadata
            "createdAt": now,
            "collegeId": college_id
        }
    ]
    
    audit_logs_coll.insert_many(logs)
    print(f"📝 Inserted {len(logs)} mock log entries")
    
    # 3. Run Aggregation (Logic from dashboard.py)
    pipeline = [
        {
            "$match": {
                "actorId": college_id,
                "category": AuditService.CATEGORY_CREDIT,
                "createdAt": {"$gte": start_of_month},
                "action": {"$regex": "^Approved"}
            }
        },
        {
            "$group": {
                "_id": None,
                "total": {"$sum": "$metadata.amount"}
            }
        }
    ]
    
    print("🔍 Running aggregation...")
    usage_result = list(audit_logs_coll.aggregate(pipeline))
    credits_used_this_month = usage_result[0]['total'] if usage_result else 0
    
    print(f"📊 Calculated Credits Used This Month: {credits_used_this_month}")
    
    # 4. Clean up
    audit_logs_coll.delete_many({"actorId": college_id})
    print("🧹 Cleaned up test data")
    
    # 5. Verification
    expected = 15 # 10 + 5
    if credits_used_this_month == expected:
        print(f"✅ SUCCESS: Logic correctly summed current month credits ({expected})")
    else:
        print(f"❌ FAILURE: Expected {expected}, got {credits_used_this_month}")
        sys.exit(1)

if __name__ == "__main__":
    test_credit_aggregation()
