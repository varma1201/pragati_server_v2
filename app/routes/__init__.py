def register_blueprints(app):
    from app.routes.auth import auth_bp
    from app.routes.users import users_bp
    from app.routes.ideas import ideas_bp
    from app.routes.credits import credits_bp
    from app.routes.analytics import analytics_bp
    from app.routes.psychometric import psychometric_bp
    from app.routes.coordinator import coordinator_bp
    from app.routes.mentors import mentors_bp
    from app.routes.teams import teams_bp
    from app.routes.admin import admin_bp
    from app.routes.notifications import notifications_bp
    from app.routes.search import search_bp
    from app.routes.reports import reports_bp
    from app.routes.reports_pdf import reports_pdf_bp
    from app.routes.principal import principal_bp
    from app.routes.audit import audit_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.plans import plans_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(ideas_bp)
    app.register_blueprint(credits_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(psychometric_bp)
    app.register_blueprint(coordinator_bp)  
    app.register_blueprint(mentors_bp)
    app.register_blueprint(teams_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(reports_pdf_bp)
    app.register_blueprint(principal_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(plans_bp)