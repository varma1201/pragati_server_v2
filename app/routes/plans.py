from flask import Blueprint, request, jsonify, current_app
from app.middleware.auth import requires_role
from app.database.mongo import db
from app.utils.validators import clean_doc
from datetime import datetime, timezone
from bson import ObjectId

plans_bp = Blueprint('plans', __name__, url_prefix='/api/plans')

# Collections
plans_coll = db['plans']
subscriptions_coll = db['subscriptions']
credit_purchases_coll = db['credit_purchases']
platform_config_coll = db['platform_config']
users_coll = db['users']

# =========================================================================
# SUPER ADMIN - PLAN MANAGEMENT (CRUD)
# =========================================================================

@plans_bp.route('/admin/all', methods=['GET'])
@requires_role(['super_admin'])
def get_all_plans():
    """Get all subscription plans (Super Admin)"""
    print("🚀 Fetching all plans...")
    try:
        interval = request.args.get('interval', None)  # 'monthly' or 'yearly'
        
        query = {"isDeleted": {"$ne": True}}
        if interval:
            query["interval"] = interval
        
        plans = list(plans_coll.find(query).sort("minCredits", 1))
        
        return jsonify({
            "success": True,
            "data": [clean_doc(plan) for plan in plans],
            "total": len(plans)
        }), 200
        
    except Exception as e:
        print(f"❌ Error fetching plans: {e}")
        return jsonify({"error": str(e)}), 500


@plans_bp.route('/admin/create', methods=['POST'])
@requires_role(['super_admin'])
def create_plan():
    """Create a new subscription plan (Super Admin)"""
    try:
        caller_id = request.user_id
        body = request.get_json(force=True)
        
        # Validate required fields
        required = ['name', 'interval', 'pricePerCredit', 'minCredits', 'totalAmount', 'features']
        for field in required:
            if field not in body:
                return jsonify({"error": f"Missing required field: {field}"}), 400
        
        # Generate plan ID
        plan_id = f"PLAN-{ObjectId()}"
        
        plan_doc = {
            "_id": plan_id,
            "name": body['name'],
            "interval": body['interval'],  # 'monthly' or 'yearly'
            "pricePerCredit": float(body['pricePerCredit']),
            "minCredits": int(body['minCredits']),
            "totalAmount": float(body['totalAmount']),
            "features": body['features'] if isinstance(body['features'], list) else body['features'].split(','),
            "enabled": body.get('enabled', True),
            "isDeleted": False,
            "createdBy": str(caller_id),
            "createdAt": datetime.now(timezone.utc),
            "updatedAt": datetime.now(timezone.utc)
        }
        
        plans_coll.insert_one(plan_doc)
        
        # Log audit
        from app.services.audit_service import AuditService
        AuditService.log_action(
            actor_id=caller_id,
            action=f"Created plan: {body['name']}",
            category=AuditService.CATEGORY_SYSTEM,
            target_id=plan_id,
            target_type="plan"
        )
        
        return jsonify({
            "success": True,
            "message": "Plan created successfully",
            "data": clean_doc(plan_doc)
        }), 201
        
    except Exception as e:
        print(f"❌ Error creating plan: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@plans_bp.route('/admin/update/<plan_id>', methods=['PUT'])
@requires_role(['super_admin'])
def update_plan(plan_id):
    """Update a subscription plan (Super Admin)"""
    try:
        caller_id = request.user_id
        body = request.get_json(force=True)
        
        # ✅ Convert plan_id string to ObjectId
        try:
            if isinstance(plan_id, str):
                plan_id_obj = ObjectId(plan_id)
            else:
                plan_id_obj = plan_id
        except Exception as e:
            return jsonify({"error": "Invalid plan ID format"}), 400
        
        # Check if plan exists (use ObjectId)
        plan = plans_coll.find_one({"_id": plan_id_obj, "isDeleted": {"$ne": True}})
        if not plan:
            return jsonify({"error": "Plan not found"}), 404
        
        # Build update data
        update_data = {
            "updatedAt": datetime.now(timezone.utc),
            "updatedBy": str(caller_id)
        }
        
        # Update allowed fields
        allowed_fields = ['name', 'pricePerCredit', 'minCredits', 'totalAmount', 'features', 'enabled']
        for field in allowed_fields:
            if field in body:
                if field == 'features' and isinstance(body[field], str):
                    update_data[field] = [f.strip() for f in body[field].split(',')]
                else:
                    update_data[field] = body[field]
        
        plans_coll.update_one(
            {"_id": plan_id_obj},  # ✅ Use ObjectId
            {"$set": update_data}
        )
        
        # Log audit
        from app.services.audit_service import AuditService
        AuditService.log_action(
            actor_id=caller_id,
            action=f"Updated plan: {plan.get('name')}",
            category=AuditService.CATEGORY_SYSTEM,
            target_id=str(plan_id_obj),  # ✅ Convert to string for audit
            target_type="plan"
        )
        
        return jsonify({
            "success": True,
            "message": "Plan updated successfully"
        }), 200
        
    except Exception as e:
        print(f"❌ Error updating plan: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@plans_bp.route('/admin/delete/<plan_id>', methods=['DELETE'])
@requires_role(['super_admin'])
def delete_plan(plan_id):
    """Soft delete a subscription plan (Super Admin)"""
    try:
        caller_id = request.user_id
        
        # ✅ Convert plan_id string to ObjectId
        try:
            if isinstance(plan_id, str):
                plan_id_obj = ObjectId(plan_id)
            else:
                plan_id_obj = plan_id
        except Exception as e:
            return jsonify({"error": "Invalid plan ID format"}), 400
        
        # Check if plan exists
        plan = plans_coll.find_one({"_id": plan_id_obj, "isDeleted": {"$ne": True}})
        if not plan:
            return jsonify({"error": "Plan not found"}), 404
        
        # Soft delete
        plans_coll.update_one(
            {"_id": plan_id_obj},  # ✅ Use ObjectId
            {"$set": {
                "isDeleted": True,
                "deletedAt": datetime.now(timezone.utc),
                "deletedBy": str(caller_id)
            }}
        )
        
        # Log audit
        from app.services.audit_service import AuditService
        AuditService.log_action(
            actor_id=caller_id,
            action=f"Deleted plan: {plan.get('name')}",
            category=AuditService.CATEGORY_SYSTEM,
            target_id=str(plan_id_obj),  # ✅ Convert to string for audit
            target_type="plan"
        )
        
        return jsonify({
            "success": True,
            "message": "Plan deleted successfully"
        }), 200
        
    except Exception as e:
        print(f"❌ Error deleting plan: {e}")
        return jsonify({"error": str(e)}), 500


# =========================================================================
# INDIVIDUAL CREDIT PRICE CONFIGURATION
# =========================================================================

@plans_bp.route('/admin/individual-credit-price', methods=['GET'])
@requires_role(['super_admin'])
def get_individual_credit_price():
    """Get current individual credit price (Super Admin)"""
    try:
        config = platform_config_coll.find_one({"key": "individual_credit_price"})
        
        if not config:
            # Set default price
            default_price = 800
            platform_config_coll.insert_one({
                "key": "individual_credit_price",
                "value": default_price,
                "createdAt": datetime.now(timezone.utc)
            })
            price = default_price
        else:
            price = config.get('value', 800)
        
        return jsonify({
            "success": True,
            "price": price
        }), 200
        
    except Exception as e:
        print(f"❌ Error fetching individual credit price: {e}")
        return jsonify({"error": str(e)}), 500


@plans_bp.route('/admin/individual-credit-price', methods=['PUT'])
@requires_role(['super_admin'])
def update_individual_credit_price():
    """Update individual credit price (Super Admin)"""
    try:
        caller_id = request.user_id
        body = request.get_json(force=True)
        
        new_price = body.get('price')
        if not new_price or new_price <= 0:
            return jsonify({"error": "Invalid price"}), 400
        
        platform_config_coll.update_one(
            {"key": "individual_credit_price"},
            {
                "$set": {
                    "value": float(new_price),
                    "updatedAt": datetime.now(timezone.utc),
                    "updatedBy": str(caller_id)
                }
            },
            upsert=True
        )
        
        # Log audit
        from app.services.audit_service import AuditService
        AuditService.log_action(
            actor_id=caller_id,
            action=f"Updated individual credit price to ₹{new_price}",
            category=AuditService.CATEGORY_SYSTEM,
            metadata={"newPrice": new_price}
        )
        
        return jsonify({
            "success": True,
            "message": "Individual credit price updated successfully",
            "price": new_price
        }), 200
        
    except Exception as e:
        print(f"❌ Error updating individual credit price: {e}")
        return jsonify({"error": str(e)}), 500


# =========================================================================
# COLLEGE ADMIN - VIEW & PURCHASE PLANS
# =========================================================================

@plans_bp.route('/available', methods=['GET'])
@requires_role(['college_admin'])
def get_available_plans():
    """Get available plans for purchase (College Admin)"""
    try:
        interval = request.args.get('interval', 'monthly')
        
        plans = list(plans_coll.find({
            "interval": interval,
            "enabled": True,
            "isDeleted": {"$ne": True}
        }).sort("minCredits", 1))
        
        return jsonify({
            "success": True,
            "data": [clean_doc(plan) for plan in plans],
            "total": len(plans)
        }), 200
        
    except Exception as e:
        print(f"❌ Error fetching available plans: {e}")
        return jsonify({"error": str(e)}), 500


@plans_bp.route('/purchase', methods=['POST'])
@requires_role(['college_admin'])
def purchase_plan():
    """Purchase a subscription plan (College Admin) - Mock Payment"""
    try:
        caller_id = request.user_id
        body = request.get_json(force=True)
        
        print("=" * 80)
        print("💳 PLAN PURCHASE REQUEST")
        print(f"   Caller ID: {caller_id}")
        print(f"   Body: {body}")
        
        plan_id = body.get('planId')
        if not plan_id:
            print("❌ Error: Plan ID not provided")
            return jsonify({"error": "Plan ID required"}), 400
        
        print(f"   Plan ID received: {plan_id}")
        
        # ✅ Convert plan_id string to ObjectId
        try:
            if isinstance(plan_id, str):
                plan_id_obj = ObjectId(plan_id)
            else:
                plan_id_obj = plan_id
        except Exception as e:
            print(f"❌ Error: Invalid plan ID format - {e}")
            return jsonify({"error": "Invalid plan ID format"}), 400
        
        print(f"   Plan ID ObjectId: {plan_id_obj}")
        
        # Get plan details (use ObjectId)
        plan = plans_coll.find_one({"_id": plan_id_obj, "enabled": True, "isDeleted": {"$ne": True}})
        if not plan:
            print(f"❌ Error: Plan not found")
            return jsonify({"error": "Plan not found or not available"}), 404
        
        print(f"   Plan found: {plan.get('name')}")
        
        # Convert caller_id to ObjectId
        if isinstance(caller_id, str):
            caller_id = ObjectId(caller_id)
        
        # Get college admin details
        admin = users_coll.find_one({"_id": caller_id})
        if not admin:
            print(f"❌ Error: Admin user not found")
            return jsonify({"error": "User not found"}), 404
        
        print(f"   Admin: {admin.get('name')}")
        
        if admin.get('role') == 'college_admin':
            college_id = str(caller_id)  # Principal's _id is the collegeId
        else:
            # For other roles, get collegeId field
            college_id = admin.get('collegeId')
        
        if not college_id:
            print(f"❌ Error: College ID not found in admin profile")
            print(f"   Admin role: {admin.get('role')}")
            print(f"   Admin _id: {caller_id}")
            return jsonify({"error": "College ID not found"}), 400
        
        print(f"   College ID: {college_id}")
                
        # Check if there's an active subscription
        active_subscription = subscriptions_coll.find_one({
            "collegeId": college_id,
            "status": "active",
            "isDeleted": {"$ne": True}
        })
        
        if active_subscription:
            print(f"❌ Error: Active subscription already exists")
            return jsonify({
                "error": "You already have an active subscription. Please cancel it before purchasing a new plan."
            }), 409
        
        # Calculate expiry date
        from datetime import timedelta
        if plan['interval'] == 'yearly':
            expiry_date = datetime.now(timezone.utc) + timedelta(days=365)
        else:  # monthly
            expiry_date = datetime.now(timezone.utc) + timedelta(days=30)
        
        # Create subscription
        subscription_id = ObjectId()
        subscription_doc = {
            "_id": subscription_id,
            "collegeId": college_id,
            "adminId": str(caller_id),
            "adminName": admin.get('name', 'Unknown'),
            "adminEmail": admin.get('email', ''),
            "planId": str(plan_id_obj),  # ✅ FIX: Store as string, not ObjectId
            "planName": plan['name'],
            "interval": plan['interval'],
            "creditsAllocated": plan['minCredits'],
            "creditsUsed": 0,
            "creditsRemaining": plan['minCredits'],
            "pricePerCredit": plan['pricePerCredit'],
            "totalAmount": plan['totalAmount'],
            "status": "active",
            "startDate": datetime.now(timezone.utc),
            "expiryDate": expiry_date,
            "autoRenew": body.get('autoRenew', False),
            "paymentStatus": "completed",  # Mock payment - always success
            "paymentMethod": "mock",
            "transactionId": f"TXN-{subscription_id}",
            "isDeleted": False,
            "createdAt": datetime.now(timezone.utc),
            "updatedAt": datetime.now(timezone.utc)
        }
        
        print(f"   Creating subscription: {subscription_id}")
        subscriptions_coll.insert_one(subscription_doc)
        
        # Update college admin's credit quota
        print(f"   Adding {plan['minCredits']} credits to admin")
        users_coll.update_one(
            {"_id": caller_id},
            {"$inc": {"creditQuota": plan['minCredits']}}
        )
        
        # Log audit
        from app.services.audit_service import AuditService
        AuditService.log_action(
            actor_id=caller_id,
            action=f"Purchased plan: {plan['name']} ({plan['minCredits']} credits)",
            category="subscription",
            target_id=str(subscription_id),
            target_type="subscription",
            metadata={
                "planId": str(plan_id_obj),  # ✅ Store as string in metadata too
                "credits": plan['minCredits'],
                "amount": plan['totalAmount']
            }
        )
        
        print(f"✅ Plan purchased successfully!")
        print("=" * 80)
        
        return jsonify({
            "success": True,
            "message": f"Plan purchased successfully! {plan['minCredits']} credits added.",
            "subscription": clean_doc(subscription_doc)
        }), 201
        
    except Exception as e:
        print("=" * 80)
        print(f"❌ Error purchasing plan: {e}")
        print("=" * 80)
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@plans_bp.route('/my-subscription', methods=['GET'])
@requires_role(['college_admin'])
def get_my_subscription():
    """Get current active subscription (College Admin)"""
    try:
        caller_id = request.user_id
        
        if isinstance(caller_id, str):
            caller_id = ObjectId(caller_id)
        
        # Get college admin details
        admin = users_coll.find_one({"_id": caller_id})
        if not admin:
            return jsonify({"error": "User not found"}), 404
        
        # ✅ FIX: For college_admin, their _id IS the collegeId
        if admin.get('role') == 'college_admin':
            college_id = str(caller_id)  # Principal's _id is the collegeId
        else:
            # For other roles (shouldn't happen with @requires_role, but just in case)
            college_id = admin.get('collegeId')
        
        if not college_id:
            return jsonify({
                "error": "College ID not found",
                "success": False
            }), 400
        
        # Get active subscription
        subscription = subscriptions_coll.find_one({
            "collegeId": college_id,
            "status": "active",
            "isDeleted": {"$ne": True}
        })
        
        if not subscription:
            return jsonify({
                "success": True,
                "data": None,
                "message": "No active subscription"
            }), 200
        
        return jsonify({
            "success": True,
            "data": clean_doc(subscription)
        }), 200
        
    except Exception as e:
        print(f"❌ Error fetching subscription: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# =========================================================================
# INDIVIDUAL INNOVATOR - BUY SINGLE CREDITS
# =========================================================================

@plans_bp.route('/individual-price', methods=['GET'])
def get_individual_price():
    """Get current individual credit price (Public)"""
    try:
        config = platform_config_coll.find_one({"key": "individual_credit_price"})
        price = config.get('value', 800) if config else 800
        
        return jsonify({
            "success": True,
            "pricePerCredit": price
        }), 200
        
    except Exception as e:
        print(f"❌ Error fetching individual price: {e}")
        return jsonify({"error": str(e)}), 500


@plans_bp.route('/purchase-credits', methods=['POST'])
@requires_role(['individual_innovator'])
def purchase_individual_credits():
    """Purchase individual credits (Individual Innovator) - Mock Payment"""
    try:
        caller_id = request.user_id
        body = request.get_json(force=True)
        
        quantity = body.get('quantity', 1)
        if quantity <= 0:
            return jsonify({"error": "Invalid quantity"}), 400
        
        # Get current price
        config = platform_config_coll.find_one({"key": "individual_credit_price"})
        price_per_credit = config.get('value', 800) if config else 800
        
        total_amount = quantity * price_per_credit
        
        # Convert caller_id to ObjectId
        if isinstance(caller_id, str):
            caller_id = ObjectId(caller_id)
        
        # Get user details
        user = users_coll.find_one({"_id": caller_id})
        if not user:
            return jsonify({"error": "User not found"}), 404
        
        # Create purchase record
        purchase_id = ObjectId()
        purchase_doc = {
            "_id": purchase_id,
            "userId": str(caller_id),
            "userName": user.get('name', 'Unknown'),
            "userEmail": user.get('email', ''),
            "quantity": quantity,
            "pricePerCredit": price_per_credit,
            "totalAmount": total_amount,
            "paymentStatus": "completed",  # Mock payment - always success
            "paymentMethod": "mock",
            "transactionId": f"TXN-{purchase_id}",
            "isDeleted": False,
            "createdAt": datetime.now(timezone.utc)
        }
        
        credit_purchases_coll.insert_one(purchase_doc)
        
        # Update user's credit quota
        users_coll.update_one(
            {"_id": caller_id},
            {"$inc": {"creditQuota": quantity}}
        )
        
        # Log audit
        from app.services.audit_service import AuditService
        AuditService.log_action(
            actor_id=caller_id,
            action=f"Purchased {quantity} individual credits (₹{total_amount})",
            category="credit_purchase",
            target_id=str(purchase_id),
            target_type="credit_purchase",
            metadata={"quantity": quantity, "amount": total_amount}
        )
        
        return jsonify({
            "success": True,
            "message": f"Successfully purchased {quantity} credits!",
            "purchase": clean_doc(purchase_doc),
            "newCreditBalance": user.get('creditQuota', 0) + quantity
        }), 201
        
    except Exception as e:
        print(f"❌ Error purchasing credits: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@plans_bp.route('/purchase-history', methods=['GET'])
@requires_role(['individual_innovator', 'college_admin'])
def get_purchase_history():
    """Get credit purchase history"""
    try:
        caller_id = request.user_id
        
        if isinstance(caller_id, str):
            caller_id = ObjectId(caller_id)
        
        # Get purchase history
        purchases = list(credit_purchases_coll.find({
            "userId": str(caller_id),
            "isDeleted": {"$ne": True}
        }).sort("createdAt", -1))
        
        return jsonify({
            "success": True,
            "data": [clean_doc(purchase) for purchase in purchases],
            "total": len(purchases)
        }), 200
        
    except Exception as e:
        print(f"❌ Error fetching purchase history: {e}")
        return jsonify({"error": str(e)}), 500
