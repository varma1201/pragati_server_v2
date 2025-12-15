from functools import wraps
from flask import request, jsonify, current_app
from app.services.auth_service import AuthService
from app.database.mongo import users_coll
from bson import ObjectId
import traceback

def requires_auth(allowed_roles=None, allow_inactive=False):
    """
    Middleware to verify JWT token and check user roles

    Args:
        allowed_roles: List of allowed roles, e.g., ['innovator', 'individual_innovator', 'mentor']
                      If None, allows all authenticated users
        allow_inactive: If True, allows inactive users to access (e.g., for activation endpoints)
    """
    # Handle usage as @requires_auth() (no parentheses)
    # If allowed_roles is a function, it means it's being used as a decorator directly
    func = None
    if callable(allowed_roles):
        func = allowed_roles
        allowed_roles = None

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Get token from Authorization header
            auth_header = request.headers.get('Authorization', '')
            if not auth_header or not auth_header.startswith('Bearer '):
                return jsonify({"error": "Missing or invalid authorization header"}), 401

            token = auth_header.split(' ')[1]

            # Verify token
            try:
                auth_service = AuthService(current_app.config['JWT_SECRET'])
                payload = auth_service.decode_token(token)

                if not payload:
                    return jsonify({"error": "Invalid or expired token"}), 401

                # Get user from database (payload uses 'uid', not 'userId')
                user_id = payload.get('uid')
                if not user_id:
                    return jsonify({"error": "Invalid token payload"}), 401

                user = users_coll.find_one({"_id": ObjectId(user_id)})
                if not user:
                    return jsonify({"error": "User not found"}), 404

                # Get user role
                user_role = user.get('role')

                # ✅ FIX #1: Super admin bypass for isActive check
                if user_role != 'super_admin':
                    if not allow_inactive and not user.get('isActive', False):
                        return jsonify({
                            "error": "Account is not active. Please contact administrator."
                        }), 403

                # ✅ FIX #2: Better role check with logging
                if allowed_roles and user_role not in allowed_roles:
                    print(f"❌ Access denied: User role '{user_role}' not in allowed roles {allowed_roles}")
                    return jsonify({
                        "error": "Access denied. Insufficient permissions.",
                        "requiredRoles": allowed_roles,
                        "userRole": user_role
                    }), 403

                # Attach user to request context
                request.user = user
                request.user_id = str(user['_id'])
                request.user_role = user_role

                return f(*args, **kwargs)

            except Exception as e:
                print(f"Auth error: {e}")
                traceback.print_exc()
                return jsonify({"error": "Authentication failed"}), 401

        return decorated_function

    if func:
        return decorator(func)
    return decorator


def requires_role(allowed_roles):
    """
    Decorator to require specific user roles.
    Automatically applies @requires_auth().

    Args:
        allowed_roles (list): List of allowed role strings

    Usage:
        @app.route('/admin')
        @requires_role(['super_admin', 'college_admin'])
        def admin_route():
            return jsonify({"message": "Admin access"})
    """
    def decorator(f):
        @wraps(f)
        @requires_auth()  # Automatically applies authentication
        def decorated(*args, **kwargs):
            user_role = request.user_role

            if user_role not in allowed_roles:
                return jsonify({
                    "error": "Access denied",
                    "message": f"Required roles: {', '.join(allowed_roles)}",
                    "yourRole": user_role
                }), 403

            return f(*args, **kwargs)

        return decorated
    return decorator


def requires_self_or_admin(f):
    """
    Decorator to allow access to self or admin roles.
    User can access their own resources, or admins can access any.

    Usage:
        @app.route('/users/<uid>')
        @requires_self_or_admin
        def get_user(uid):
            # User can access own profile, or admin can access any
            return jsonify({"user": uid})
    """
    @wraps(f)
    @requires_auth()  # ✅ Added parentheses
    def decorated(*args, **kwargs):
        user_id = request.user_id
        user_role = request.user_role

        # Get uid from URL parameters
        uid = kwargs.get('uid') or request.view_args.get('uid')

        # Allow if accessing self
        if user_id == uid:
            return f(*args, **kwargs)

        # Allow if admin
        if user_role in ['super_admin', 'college_admin', 'ttc_coordinator']:
            return f(*args, **kwargs)

        return jsonify({"error": "Access denied"}), 403

    return decorated


def optional_auth(f):
    """
    Decorator for optional authentication.
    Attaches user info if token present, but doesn't require it.

    Usage:
        @app.route('/public')
        @optional_auth
        def public_route():
            if hasattr(request, 'user_id'):
                return jsonify({"message": f"Hello {request.user_id}"})
            return jsonify({"message": "Hello guest"})
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')

        if auth_header:
            try:
                token = auth_header.split(' ')[1] if ' ' in auth_header else auth_header
                token = token.replace('Bearer ', '').strip()

                auth_service = AuthService(current_app.config['JWT_SECRET'])
                payload = auth_service.decode_token(token)

                request.user_id = payload.get('uid')
                request.user_role = payload.get('role')
                request.token_payload = payload
                request.current_user = payload
            except Exception:
                # Silently fail - optional auth
                pass

        return f(*args, **kwargs)

    return decorated


def requires_active_user(f):
    """
    Decorator to require user account to be active.
    Checks isActive flag in user document.

    Usage:
        @app.route('/active-only')
        @requires_active_user
        def active_route():
            return jsonify({"message": "Active users only"})
    """
    @wraps(f)
    @requires_auth()  # ✅ Added parentheses
    def decorated(*args, **kwargs):
        from app.database.mongo import users_coll

        user = users_coll.find_one(
            {"_id": ObjectId(request.user_id)},
            {"isActive": 1, "isDeleted": 1, "role": 1}
        )

        if not user:
            return jsonify({"error": "User not found"}), 404

        if user.get('isDeleted'):
            return jsonify({"error": "Account deleted"}), 403

        # ✅ FIX: Super admin bypass
        if user.get('role') != 'super_admin':
            if not user.get('isActive', False):
                return jsonify({
                    "error": "Account not activated",
                    "message": "Please activate your account to access this resource"
                }), 403

        return f(*args, **kwargs)

    return decorated


def requires_college_access(f):
    """
    Decorator to verify user has access to specific college resources.
    Validates collegeId matches between user and requested resource.

    Usage:
        @app.route('/colleges/<college_id>/data')
        @requires_college_access
        def college_data(college_id):
            return jsonify({"data": "college-specific"})
    """
    @wraps(f)
    @requires_auth()  # ✅ Added parentheses
    def decorated(*args, **kwargs):
        from app.database.mongo import users_coll

        user_role = request.user_role
        user_id = request.user_id

        # ✅ FIX: Super admins bypass college checks
        if user_role == 'super_admin':
            return f(*args, **kwargs)

        # Get college_id from URL
        college_id = kwargs.get('college_id') or request.view_args.get('college_id')
        if not college_id:
            return jsonify({"error": "College ID required"}), 400

        # Verify user belongs to this college
        user = users_coll.find_one(
            {"_id": ObjectId(user_id)},
            {"collegeId": 1}
        )

        if user.get('collegeId') != college_id:
            return jsonify({"error": "Access denied to this college"}), 403

        return f(*args, **kwargs)

    return decorated


def log_request(f):
    """
    Decorator to log API requests with user info.

    Usage:
        @app.route('/api/important')
        @requires_auth()
        @log_request
        def important_route():
            return jsonify({"data": "important"})
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        user_id = getattr(request, 'user_id', 'anonymous')
        user_role = getattr(request, 'user_role', 'unknown')

        print(f"📝 {request.method} {request.path} | User: {user_id} | Role: {user_role}")

        return f(*args, **kwargs)

    return decorated