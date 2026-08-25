# Standard library imports
from urllib.parse import quote_plus

# Third-party imports
from flask import Flask, render_template
from flask_login import current_user
from flask_migrate import Migrate
from werkzeug.exceptions import HTTPException

# Local imports
from config import config
from extensions import db, login_manager, mail
from models import User, Requisition, PendingRemoval, Notification, DeletionRequest
from template_filters import format_relative_time, to_float
from routes.auth import auth
from routes.main import main
from routes.products import products
from routes.requisitions import requisitions
from routes.admin import admin
from routes.scanner import scanner
from routes.api import api
from routes.logs import logs
from routes.misc import misc
from routes.pending_removals import pending_removals
from routes.companies import companies
from routes.store import store
from routes.routes import receiving_bp
from routes.reports import reports

# Import user loader function
def load_user(user_id):
    return User.query.get(int(user_id))


def create_app(config_name='default'):
    """Application factory pattern"""
    app = Flask(__name__)
    
    # Load configuration
    app.config.from_object(config[config_name])
    
    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)
    
    # Initialize Flask-Migrate
    migrate = Migrate(app, db)
    
    # Configure login manager
    login_manager.user_loader(load_user)
    
    # Register template filters
    app.template_filter('relative_time')(format_relative_time)
    app.template_filter('to_float')(to_float)
    
    # Add custom filter for decimal formatting
    @app.template_filter('decimal_format')
    def decimal_format(value, decimal_places=2):
        """Format a number to specified decimal places (default 2)"""
        try:
            return f"{float(value):.{decimal_places}f}"
        except (ValueError, TypeError):
            return value
    
    # Add custom filter for URL encoding
    @app.template_filter('urlencode')
    def urlencode_filter(value):
        """URL encode a string for use in URLs"""
        if value is None:
            return ''
        return quote_plus(str(value))
    
    # Add context processor to provide global variables to templates
    @app.context_processor
    def inject_global_vars():
        """Provide global variables to all templates"""
        if current_user.is_authenticated:
            # Count pending requisitions for current user's company
            pending_requisition_count = Requisition.query.filter_by(
                status='Pending',
                company_id=current_user.company_id
            ).count()
            
            # Count pending removals based on user role
            if current_user.role == 'WH-Admin':
                # WH-Admin can only see their own pending removals
                pending_removal_count = PendingRemoval.query.filter_by(
                    status='Pending',
                    requested_by=current_user.id
                ).count()
            else:
                # SYS-Admin and Company-Admin can see all pending removals in their company
                pending_removal_count = PendingRemoval.query.filter_by(
                    status='Pending',
                    company_id=current_user.company_id
                ).count()
            
            # Count requisitions awaiting delivery (approved or Dispatched)
            pending_receiving_count = Requisition.query.filter(
                Requisition.company_id == current_user.company_id,
                Requisition.status.in_(['approved', 'Dispatched'])
            ).count()

            # Count pending deletion requests for Company-Admin/SYS-Admin
            pending_deletion_count = 0
            if current_user.role in ('Company-Admin', 'SYS-Admin'):
                if current_user.role == 'SYS-Admin' and current_user.company_id is None:
                    pending_deletion_count = DeletionRequest.query.filter_by(status='Pending').count()
                else:
                    pending_deletion_count = DeletionRequest.query.filter_by(status='Pending', company_id=current_user.company_id).count()

            return dict(
                current_user=current_user,
                pending_requisition_count=pending_requisition_count,
                pending_removal_count=pending_removal_count,
                pending_receiving_count=pending_receiving_count,
                pending_deletion_count=pending_deletion_count,
                notification_count=Notification.query.filter_by(
                    user_id=current_user.id, is_read=False
                ).count()
            )
        return dict(current_user=current_user)
    
    # Register blueprints
    app.register_blueprint(auth)
    app.register_blueprint(main)
    app.register_blueprint(products)
    app.register_blueprint(requisitions)
    app.register_blueprint(admin)
    app.register_blueprint(scanner)
    app.register_blueprint(api)
    app.register_blueprint(logs)
    app.register_blueprint(misc)
    app.register_blueprint(pending_removals)
    app.register_blueprint(companies)
    app.register_blueprint(receiving_bp)
    app.register_blueprint(reports)
    app.register_blueprint(store)
    
    # Error handlers
    @app.errorhandler(404)
    def not_found_error(error):
        # Provide default values for template variables used in base-sidebar.html
        # These are needed because the context processor isn't called for error handlers
        if current_user.is_authenticated:
            pending_requisition_count = Requisition.query.filter_by(
                status='Pending',
                company_id=current_user.company_id
            ).count()
            
            if current_user.role == 'WH-Admin':
                pending_removal_count = PendingRemoval.query.filter_by(
                    status='Pending',
                    requested_by=current_user.id
                ).count()
            else:
                pending_removal_count = PendingRemoval.query.filter_by(
                    status='Pending',
                    company_id=current_user.company_id
                ).count()
                
            pending_receiving_count = Requisition.query.filter(
                Requisition.company_id == current_user.company_id,
                Requisition.status.in_(['approved', 'Dispatched'])
            ).count()

            notification_count = Notification.query.filter_by(
                user_id=current_user.id, is_read=False
            ).count()

            pending_deletion_count = 0
            if current_user.role in ('Company-Admin', 'SYS-Admin'):
                if current_user.role == 'SYS-Admin' and current_user.company_id is None:
                    pending_deletion_count = DeletionRequest.query.filter_by(status='Pending').count()
                else:
                    pending_deletion_count = DeletionRequest.query.filter_by(status='Pending', company_id=current_user.company_id).count()
        else:
            pending_requisition_count = 0
            pending_removal_count = 0
            pending_receiving_count = 0
            pending_deletion_count = 0
            notification_count = 0

        return render_template('shared/404.html', 
                             pending_requisition_count=pending_requisition_count,
                             pending_removal_count=pending_removal_count,
                             pending_receiving_count=pending_receiving_count,
                             pending_deletion_count=pending_deletion_count,
                             notification_count=notification_count), 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        if current_user.is_authenticated:
            pending_requisition_count = Requisition.query.filter_by(
                status='Pending',
                company_id=current_user.company_id
            ).count()
            
            if current_user.role == 'WH-Admin':
                pending_removal_count = PendingRemoval.query.filter_by(
                    status='Pending',
                    requested_by=current_user.id
                ).count()
            else:
                pending_removal_count = PendingRemoval.query.filter_by(
                    status='Pending',
                    company_id=current_user.company_id
                ).count()

            pending_receiving_count = Requisition.query.filter(
                Requisition.company_id == current_user.company_id,
                Requisition.status.in_(['approved', 'Dispatched'])
            ).count()

            pending_deletion_count = 0
            if current_user.role in ('Company-Admin', 'SYS-Admin'):
                if current_user.role == 'SYS-Admin' and current_user.company_id is None:
                    pending_deletion_count = DeletionRequest.query.filter_by(status='Pending').count()
                else:
                    pending_deletion_count = DeletionRequest.query.filter_by(status='Pending', company_id=current_user.company_id).count()

            notification_count = Notification.query.filter_by(
                user_id=current_user.id, is_read=False
            ).count()
        else:
            pending_requisition_count = 0
            pending_removal_count = 0
            pending_receiving_count = 0
            pending_deletion_count = 0
            notification_count = 0

        return render_template('shared/500.html',
                             pending_requisition_count=pending_requisition_count,
                             pending_removal_count=pending_removal_count,
                             pending_receiving_count=pending_receiving_count,
                             pending_deletion_count=pending_deletion_count,
                             notification_count=notification_count), 500
    
    @app.errorhandler(Exception)
    def handle_exception(e):
        # Pass through HTTP errors
        if isinstance(e, HTTPException):
            return e
        
        # Log the error for debugging
        app.logger.error(f'Unhandled exception: {e}', exc_info=True)
        
        # For non-HTTP exceptions, return a generic 500 error
        db.session.rollback()
        notification_count = 0
        pending_requisition_count = 0
        pending_removal_count = 0
        pending_receiving_count = 0
        pending_deletion_count = 0
        if current_user.is_authenticated:
            try:
                notification_count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
                pending_requisition_count = Requisition.query.filter_by(status='Pending', company_id=current_user.company_id).count()
                pending_removal_count = PendingRemoval.query.filter_by(status='Pending', company_id=current_user.company_id).count()
                pending_receiving_count = Requisition.query.filter(Requisition.company_id == current_user.company_id, Requisition.status.in_(['approved', 'Dispatched'])).count()
                if current_user.role in ('Company-Admin', 'SYS-Admin'):
                    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
                        pending_deletion_count = DeletionRequest.query.filter_by(status='Pending').count()
                    else:
                        pending_deletion_count = DeletionRequest.query.filter_by(status='Pending', company_id=current_user.company_id).count()
            except Exception:
                pass
        return render_template('shared/500.html',
                             pending_requisition_count=pending_requisition_count,
                             pending_removal_count=pending_removal_count,
                             pending_receiving_count=pending_receiving_count,
                             pending_deletion_count=pending_deletion_count,
                             notification_count=notification_count), 500
    
    # Create tables and initialize database
    with app.app_context():
        try:
            db.create_all()
            from sqlalchemy import inspect, text
            inspector = inspect(db.engine)

            # Add location column to product_batch if it doesn't exist
            try:
                columns = [c['name'] for c in inspector.get_columns('product_batch')]
                if 'location' not in columns:
                    db.session.execute(text('ALTER TABLE product_batch ADD COLUMN location VARCHAR(100)'))
                    db.session.commit()
                    app.logger.info("Added 'location' column to product_batch table")
            except Exception:
                pass  # product_batch table may not exist yet

            # ── Migrate product_batch → warehouse_product_batch ──
            try:
                inspector2 = inspect(db.engine)
                existing_tables = inspector2.get_table_names()
                if 'product_batch' in existing_tables and 'warehouse_product_batch' not in existing_tables:
                    db.session.execute(text(
                        'CREATE TABLE warehouse_product_batch AS SELECT * FROM product_batch'
                    ))
                    db.session.commit()
                    app.logger.info("Migrated product_batch data to warehouse_product_batch")
                elif 'product_batch' in existing_tables and 'warehouse_product_batch' in existing_tables:
                    wh_count = db.session.execute(text('SELECT COUNT(*) FROM warehouse_product_batch')).scalar()
                    old_count = db.session.execute(text('SELECT COUNT(*) FROM product_batch')).scalar()
                    if wh_count == 0 and old_count > 0:
                        db.session.execute(text(
                            'INSERT INTO warehouse_product_batch '
                            '(id, product_id, quantity, int_quantity, exp_date, supplier_name, location, added_on, sub_barcode) '
                            'SELECT id, product_id, quantity, int_quantity, exp_date, supplier_name, location, added_on, sub_barcode '
                            'FROM product_batch'
                        ))
                        db.session.commit()
                        app.logger.info(f"Migrated {old_count} rows from product_batch to warehouse_product_batch")
            except Exception as e:
                db.session.rollback()
                app.logger.warning(f"Warehouse batch migration note: {e}")

            # Ensure store_product_batch table exists (empty by default)
            try:
                inspector3 = inspect(db.engine)
                if 'store_product_batch' not in inspector3.get_table_names():
                    db.create_all()
                    app.logger.info("Created store_product_batch table")
            except Exception as e:
                db.session.rollback()
                app.logger.warning(f"Store batch table creation note: {e}")

            # Add is_optional column to requisition_item if it doesn't exist
            req_item_columns = [c['name'] for c in inspector.get_columns('requisition_item')]
            if 'is_optional' not in req_item_columns:
                db.session.execute(text('ALTER TABLE requisition_item ADD COLUMN is_optional BOOLEAN NOT NULL DEFAULT 0'))
                db.session.commit()
                app.logger.info("Added 'is_optional' column to requisition_item table")

            # Add station column to product if it doesn't exist
            product_columns = [c['name'] for c in inspector.get_columns('product')]
            if 'station' not in product_columns:
                db.session.execute(text("ALTER TABLE product ADD COLUMN station VARCHAR(50)"))
                db.session.commit()
                app.logger.info("Added 'station' column to product table")

            # Add station column to requisition if it doesn't exist
            req_columns = [c['name'] for c in inspector.get_columns('requisition')]
            if 'station' not in req_columns:
                db.session.execute(text("ALTER TABLE requisition ADD COLUMN station VARCHAR(50)"))
                db.session.commit()
                app.logger.info("Added 'station' column to requisition table")

            # Create deletion_request table if it doesn't exist
            existing_tables = inspector.get_table_names()
            if 'deletion_request' not in existing_tables:
                db.create_all()
                app.logger.info("Created 'deletion_request' table")
            else:
                # Ensure product_history_id is nullable (for approved requests where history is deleted)
                try:
                    dr_cols = [c['name'] for c in inspector.get_columns('deletion_request')]
                    if 'product_history_id' in dr_cols:
                        # SQLite: rebuild table to make column nullable
                        from sqlalchemy import text as sa_text
                        db.session.execute(sa_text('''
                            CREATE TABLE IF NOT EXISTS deletion_request_new (
                                id INTEGER PRIMARY KEY,
                                product_history_id INTEGER REFERENCES product_history(id) ON DELETE SET NULL,
                                product_id INTEGER NOT NULL REFERENCES product(id),
                                trxn_code VARCHAR(20) NOT NULL,
                                quantity_in FLOAT DEFAULT 0.0,
                                quantity_out FLOAT DEFAULT 0.0,
                                net_change FLOAT DEFAULT 0.0,
                                reason TEXT NOT NULL,
                                status VARCHAR(20) DEFAULT 'Pending',
                                requested_by INTEGER NOT NULL REFERENCES user(id),
                                reviewed_by INTEGER REFERENCES user(id),
                                review_remarks TEXT,
                                requested_at DATETIME,
                                reviewed_at DATETIME,
                                company_id INTEGER NOT NULL REFERENCES company(id)
                            )
                        '''))
                        db.session.execute(sa_text('INSERT INTO deletion_request_new SELECT * FROM deletion_request'))
                        db.session.execute(sa_text('DROP TABLE deletion_request'))
                        db.session.execute(sa_text('ALTER TABLE deletion_request_new RENAME TO deletion_request'))
                        db.session.commit()
                        app.logger.info("Made deletion_request.product_history_id nullable")
                except Exception as e:
                    db.session.rollback()
                    app.logger.warning(f"deletion_request migration note: {e}")

            # ── Add warehouse/store quantity columns to product table ──
            try:
                inspector = inspect(db.engine)
                prod_cols = [c['name'] for c in inspector.get_columns('product')]
                if 'warehouse_qty' not in prod_cols:
                    db.session.execute(text('ALTER TABLE product ADD COLUMN warehouse_qty FLOAT NOT NULL DEFAULT 0.0'))
                    db.session.execute(text('ALTER TABLE product ADD COLUMN warehouse_initial_qty FLOAT NOT NULL DEFAULT 0.0'))
                    db.session.execute(text('ALTER TABLE product ADD COLUMN store_qty FLOAT NOT NULL DEFAULT 0.0'))
                    db.session.execute(text('ALTER TABLE product ADD COLUMN store_initial_qty FLOAT NOT NULL DEFAULT 0.0'))
                    db.session.commit()
                    app.logger.info("Added warehouse_qty, warehouse_initial_qty, store_qty, store_initial_qty to product")
                    # Migrate existing quantity data: warehouse gets the current qty, store starts at 0
                    try:
                        db.session.execute(text(
                            'UPDATE product SET warehouse_qty = quantity, warehouse_initial_qty = initial_quantity, '
                            'store_qty = 0, store_initial_qty = 0 '
                            'WHERE warehouse_qty = 0 AND quantity > 0'
                        ))
                        db.session.commit()
                        app.logger.info("Migrated existing quantities to warehouse_qty")
                    except Exception as e2:
                        db.session.rollback()
                        app.logger.warning(f"Warehouse qty migration note: {e2}")
            except Exception as e:
                db.session.rollback()
                app.logger.warning(f"Warehouse/store qty migration note: {e}")

            # ── Add warehouse/store audit columns to stock_audit table ──
            try:
                inspector = inspect(db.engine)
                sa_cols = [c['name'] for c in inspector.get_columns('stock_audit')]
                new_audit_cols = [
                    ('warehouse_recorded_qty', 'FLOAT NOT NULL DEFAULT 0.0'),
                    ('warehouse_actual_qty', 'FLOAT NOT NULL DEFAULT 0.0'),
                    ('store_recorded_qty', 'FLOAT NOT NULL DEFAULT 0.0'),
                    ('store_actual_qty', 'FLOAT NOT NULL DEFAULT 0.0'),
                ]
                for col_name, col_def in new_audit_cols:
                    if col_name not in sa_cols:
                        db.session.execute(text(f'ALTER TABLE stock_audit ADD COLUMN {col_name} {col_def}'))
                db.session.commit()
                app.logger.info("Added warehouse/store audit columns to stock_audit")
            except Exception as e:
                db.session.rollback()
                app.logger.warning(f"Stock audit migration note: {e}")

        except Exception as e:
            db.session.rollback()
            app.logger.warning(f"Database initialization error (may be expected during first run): {e}")
    
    return app


def inspect_table_exists(table_name):
    """Check if a table exists in the database"""
    try:
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        return table_name in inspector.get_table_names()
    except:
        return False


# Create the application instance
app = create_app()

# Import routes after app creation to avoid circular imports
# Routes are already imported above for blueprint registration

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)