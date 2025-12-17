"""
Seed script to populate initial subscription plans
Run: python scripts/seed_plans.py
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.database.mongo import db
from datetime import datetime, timezone
from bson import ObjectId  # ✅ Import ObjectId

# Initialize Flask app
app = create_app()

# Plans data
PLANS = [
    # Monthly Plans
    {
        "name": "Essential Monthly",
        "pricePerCredit": 500,
        "minCredits": 20,
        "totalAmount": 10000,
        "features": ["20 Idea Submissions", "Basic Feedback", "5 TTCs"],
        "enabled": True,
        "interval": "monthly",
    },
    {
        "name": "Advance Monthly",
        "pricePerCredit": 490,
        "minCredits": 50,
        "totalAmount": 24500,
        "features": [
            "50 Idea Submissions",
            "Detailed Feedback",
            "10 TTCs",
            "2 Consultations",
        ],
        "enabled": True,
        "interval": "monthly",
    },
    {
        "name": "Advance Pro Monthly",
        "pricePerCredit": 475,
        "minCredits": 100,
        "totalAmount": 47500,
        "features": [
            "Unlimited Idea Submissions",
            "Premium Feedback",
            "15 TTCs",
            "Unlimited Consultations",
        ],
        "enabled": True,
        "interval": "monthly",
    },
    
    # Yearly Plans
    {
        "name": "Essential Yearly",
        "pricePerCredit": 450,
        "minCredits": 240,
        "totalAmount": 108000,
        "features": [
            "240 Idea Submissions",
            "Basic Feedback",
            "5 TTCs",
            "10% Discount",
        ],
        "enabled": True,
        "interval": "yearly",
    },
    {
        "name": "Advance Yearly",
        "pricePerCredit": 440,
        "minCredits": 600,
        "totalAmount": 264000,
        "features": [
            "600 Idea Submissions",
            "Detailed Feedback",
            "10 TTCs",
            "24 Consultations",
            "12% Discount",
        ],
        "enabled": True,
        "interval": "yearly",
    },
    {
        "name": "Advance Pro Yearly",
        "pricePerCredit": 425,
        "minCredits": 1200,
        "totalAmount": 510000,
        "features": [
            "Unlimited Idea Submissions",
            "Premium Feedback",
            "15 TTCs",
            "Unlimited Consultations",
            "15% Discount",
        ],
        "enabled": True,
        "interval": "yearly",
    },
    
    # Enterprise Plans
    {
        "name": "Enterprise Monthly",
        "pricePerCredit": 0,
        "minCredits": 0,
        "totalAmount": 0,
        "features": [
            "Custom Limits",
            "Dedicated Support",
            "Tailored Solutions",
            "Contact Us for Pricing",
        ],
        "enabled": True,
        "interval": "monthly",
    },
    {
        "name": "Enterprise Yearly",
        "pricePerCredit": 0,
        "minCredits": 0,
        "totalAmount": 0,
        "features": [
            "Custom Limits",
            "Dedicated Support",
            "Tailored Solutions",
            "Contact Us for Pricing",
        ],
        "enabled": True,
        "interval": "yearly",
    },
]


def seed_plans():
    """Insert all plans into the database"""
    with app.app_context():
        plans_coll = db['plans']
        
        print("=" * 80)
        print("🌱 SEEDING SUBSCRIPTION PLANS")
        print("=" * 80)
        
        inserted_count = 0
        updated_count = 0
        
        for plan in PLANS:
            # Check if plan already exists by name and interval
            existing_plan = plans_coll.find_one({
                "name": plan['name'],
                "interval": plan['interval'],
                "isDeleted": {"$ne": True}
            })
            
            if existing_plan:
                # Update existing plan
                plan_doc = {**plan}
                plan_doc['updatedAt'] = datetime.now(timezone.utc)
                plan_doc['isDeleted'] = False
                
                plans_coll.update_one(
                    {"_id": existing_plan["_id"]},
                    {"$set": plan_doc}
                )
                print(f"   ✏️  Updated: {plan['name']} ({plan['interval']}) - ID: {existing_plan['_id']}")
                updated_count += 1
            else:
                # ✅ Insert new plan with MongoDB ObjectId
                plan_doc = {**plan}
                plan_doc['_id'] = ObjectId()  # ✅ Generate new ObjectId
                plan_doc['createdAt'] = datetime.now(timezone.utc)
                plan_doc['updatedAt'] = datetime.now(timezone.utc)
                plan_doc['isDeleted'] = False
                plan_doc['createdBy'] = "system"
                
                plans_coll.insert_one(plan_doc)
                print(f"   ✅ Inserted: {plan['name']} ({plan['interval']}) - ID: {plan_doc['_id']}")
                inserted_count += 1
        
        print("=" * 80)
        print(f"📊 SUMMARY:")
        print(f"   ✅ Inserted: {inserted_count}")
        print(f"   ✏️  Updated: {updated_count}")
        print(f"   📦 Total Plans: {len(PLANS)}")
        print("=" * 80)
        
        # Set default individual credit price if not exists
        platform_config_coll = db['platform_config']
        config = platform_config_coll.find_one({"key": "individual_credit_price"})
        
        if not config:
            platform_config_coll.insert_one({
                "key": "individual_credit_price",
                "value": 800,
                "createdAt": datetime.now(timezone.utc),
                "createdBy": "system"
            })
            print("\n💰 Set default individual credit price: ₹800")
        else:
            print(f"\n💰 Individual credit price: ₹{config.get('value', 800)}")
        
        print("\n✅ Seeding complete!\n")


if __name__ == "__main__":
    try:
        seed_plans()
    except Exception as e:
        print(f"\n❌ Error seeding plans: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
