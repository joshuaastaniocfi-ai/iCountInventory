# Standard library imports
from datetime import datetime
from zoneinfo import ZoneInfo


# Third-party imports
from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash
import secrets
import json

# Local imports
from extensions import db


# Many-to-many relationship table for users handling multiple companies/warehouses
user_companies = db.Table('user_companies',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), primary_key=True),
    db.Column('company_id', db.Integer, db.ForeignKey('company.id', ondelete='CASCADE'), primary_key=True)
)


class Company(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Manila")))
    franchise_name = db.Column(db.String(150), nullable=True)
    logo = db.Column(db.String(200), nullable=True)

    # Relationships
    users = db.relationship('User', backref='company')
    products = db.relationship('Product', backref='company')
    requisitions = db.relationship('Requisition', foreign_keys='Requisition.company_id', backref='company')
    stock_audits = db.relationship('StockAudit', backref='company')
    product_histories = db.relationship('ProductHistory', backref='company')
    pending_removals = db.relationship('PendingRemoval', backref='company')
    spoilages = db.relationship('Spoilage', backref='company')
    oth_records = db.relationship('OnTheHouse', foreign_keys='OnTheHouse.company_id', backref='company')
    store_productions = db.relationship('StoreProduction', foreign_keys='StoreProduction.company_id', backref='company')


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    branch = db.Column(db.String(100))
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(50), default='User')
    email_verified = db.Column(db.Boolean, default=False)
    is_banned = db.Column(db.Boolean, default=False)
    verification_token = db.Column(db.String(100), unique=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=True)

    # Additional companies / warehouses this user handles
    handled_companies = db.relationship(
        'Company',
        secondary=user_companies,
        lazy='subquery',
        backref=db.backref('assigned_users', lazy=True)
    )

    @property
    def all_companies(self):
        """Return list of Company objects this user has access to."""
        if self.role == 'SYS-Admin' and self.company_id is None:
            return Company.query.order_by(Company.name.asc()).all()
        comps = list(self.handled_companies) if self.handled_companies else []
        if self.company and self.company not in comps:
            comps.insert(0, self.company)
        return comps

    @property
    def all_company_ids(self):
        """Return list of company IDs this user has access to."""
        return [c.id for c in self.all_companies]

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    # Treat unverified or banned users as inactive so Flask-Login refuses login
    @property
    def is_active(self):  # type: ignore[override]
        return bool(self.email_verified and not self.is_banned)

    def generate_verification_token(self):
        self.verification_token = secrets.token_urlsafe(32)
        return self.verification_token


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    barcode = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    account_title = db.Column(db.String(100), nullable=False)
    item_uom_desc = db.Column(db.String(200))
    uom_conversion = db.Column(db.String(100))
    uom = db.Column(db.String(50))
    # Legacy columns (kept for backward compatibility)
    quantity = db.Column(db.Float, nullable=False, default=0.0)
    initial_quantity = db.Column(db.Float, nullable=False, default=0.0)
    # Warehouse vs Store quantities
    warehouse_qty = db.Column(db.Float, nullable=False, default=0.0)
    warehouse_initial_qty = db.Column(db.Float, nullable=False, default=0.0)
    store_qty = db.Column(db.Float, nullable=False, default=0.0)
    store_initial_qty = db.Column(db.Float, nullable=False, default=0.0)
    low_stock_threshold = db.Column(db.Integer, default=10)
    reorder_level = db.Column(db.Integer, default=0)  # Added reorder_level column
    station = db.Column(db.String(50))  # Station type: Sandwich, Counter, Soda, Maincourse, Warehouse, Coffee Bar
    exp_date = db.Column(db.String(50))  # kept for backward compatibility
    purchase_order_place = db.Column(db.String(100))
    last_updated = db.Column(db.DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Manila")))
    is_favorite = db.Column(db.Boolean, default=False)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)

    @property
    def batches(self):
        return self.warehouse_batches

    @property
    def is_low_stock(self):
        # Check if reorder_level is set and use it for low stock determination
        if self.reorder_level > 0:
            return self.quantity <= self.reorder_level
        # Fallback to threshold-based calculation if no reorder_level is set
        if self.initial_quantity == 0:
            return False
        threshold_qty = self.initial_quantity * (self.low_stock_threshold / 100)
        return self.quantity <= threshold_qty


class WarehouseProductBatch(db.Model):
    """Batches stored in the warehouse."""
    __tablename__ = 'warehouse_product_batch'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Float, nullable=False, default=0.0)
    int_quantity = db.Column(db.Float, nullable=False, default=0.0)
    production_date = db.Column(db.Date, nullable=True)
    exp_date = db.Column(db.Date, nullable=False)
    supplier_name = db.Column(db.String(100), nullable=True)
    added_on = db.Column(db.DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Manila")))
    sub_barcode = db.Column(db.String(30), nullable=True)
    product = db.relationship('Product', backref='warehouse_batches')


class StoreProductBatch(db.Model):
    """Batches transferred to / stored in the store."""
    __tablename__ = 'store_product_batch'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Float, nullable=False, default=0.0)
    int_quantity = db.Column(db.Float, nullable=False, default=0.0)
    exp_date = db.Column(db.Date, nullable=False)
    supplier_name = db.Column(db.String(100), nullable=True)
    added_on = db.Column(db.DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Manila")))
    sub_barcode = db.Column(db.String(30), nullable=True)
    product = db.relationship('Product', backref='store_batches')


# Backward-compatible alias — existing code that imports ProductBatch still works
# This maps to WarehouseProductBatch so existing queries operate on warehouse data
ProductBatch = WarehouseProductBatch


class Requisition(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date_created = db.Column(db.DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Manila")))
    requested_by = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(50), default='Pending')
    contact_number = db.Column(db.String(20))
    branch = db.Column(db.String(50))
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    items = db.relationship('RequisitionItem', backref='requisition', cascade="all, delete-orphan")
    # Add validated field to track if requisition has been validated through scanning
    validated = db.Column(db.Boolean, default=False, nullable=False)
    # Add date fields for approval and delivery
    date_approved = db.Column(db.DateTime, nullable=True)
    date_of_delivery = db.Column(db.DateTime, nullable=True)
    station = db.Column(db.String(50))  # Station type: Sandwich, Counter, Soda, Maincourse, Warehouse, Coffee Bar
    # Variance tracking directly linked to requisition
    has_variance = db.Column(db.Boolean, default=False, nullable=True)
    variance_summary = db.Column(db.Text, nullable=True)
    variance_resolution = db.Column(db.String(50), nullable=True)
    variance_resolved_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    variance_resolved_at = db.Column(db.DateTime, nullable=True)
    variance_admin_notes = db.Column(db.Text, nullable=True)
    variance_resolver = db.relationship('User', foreign_keys=[variance_resolved_by], backref='resolved_requisition_variances')

    # Transfer requisition fields (From Company -> To Company)
    requisition_type = db.Column(db.String(50), default='store', nullable=True)  # 'store' or 'transfer'
    destination_company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=True)
    destination_company = db.relationship('Company', foreign_keys=[destination_company_id], backref='incoming_transfers')
    # Note: RequisitionItem and RequisitionBatchDeduction inherit company context through relationships


class RequisitionItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    requisition_id = db.Column(db.Integer, db.ForeignKey('requisition.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Float, nullable=False, default=0.0)  # Original quantity requested by store
    released_quantity = db.Column(db.Float, nullable=True)        # Exact quantity released by warehouse for delivery
    uom = db.Column(db.String(50), nullable=False)
    is_optional = db.Column(db.Boolean, default=False, nullable=False)
    product = db.relationship('Product')
    deductions = db.relationship('RequisitionBatchDeduction', backref='requisition_item', cascade="all, delete-orphan")
    # Note: Inherits company_id through requisition relationship


class RequisitionBatchDeduction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    requisition_item_id = db.Column(db.Integer, db.ForeignKey('requisition_item.id'), nullable=False)
    total_current_qty = db.Column(db.Float, nullable=False, default=0.0)  # Total quantity from all batches before deduction
    requested_qty = db.Column(db.Float, nullable=False, default=0.0)      # Amount requested
    remaining_qty = db.Column(db.Float, nullable=False, default=0.0)      # Amount left after deduction
    # Note: Inherits company_id through requisition_item -> requisition relationship


class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(200), nullable=False)
    details = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Manila")))
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=True)


class StockAudit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    recorded_quantity = db.Column(db.Float, nullable=False, default=0.0)
    actual_quantity = db.Column(db.Float, nullable=False, default=0.0)
    discrepancy = db.Column(db.Float, nullable=False, default=0.0)
    # Warehouse vs Store breakdown
    warehouse_recorded_qty = db.Column(db.Float, nullable=False, default=0.0)
    warehouse_actual_qty = db.Column(db.Float, nullable=False, default=0.0)
    store_recorded_qty = db.Column(db.Float, nullable=False, default=0.0)
    store_actual_qty = db.Column(db.Float, nullable=False, default=0.0)
    verified_by = db.Column(db.String(100), nullable=False)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Manila")))
    batch_label = db.Column(db.String(100), nullable=False)
    is_settled = db.Column(db.Boolean, default=False)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    product = db.relationship('Product', backref='audits')


# BatchAudit model for the batch_audit table
class BatchAudit(db.Model):
    __tablename__ = 'batch_audit'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, nullable=False)
    product_name = db.Column(db.String(100), nullable=False)
    product_uom = db.Column(db.String(50))
    batch_id = db.Column(db.Integer, nullable=False)
    batch_barcode = db.Column(db.String(100), nullable=False)
    exp_date = db.Column(db.Date)
    recorded_quantity = db.Column(db.Float, nullable=False)
    actual_quantity = db.Column(db.Float, nullable=False)
    discrepancy = db.Column(db.Float, nullable=False)
    verified_by = db.Column(db.String(100), nullable=False)
    audit_timestamp = db.Column(db.DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Manila")))
    status = db.Column(db.String(20), default='pending')
    is_settled = db.Column(db.Boolean, default=False)
    batch_label = db.Column(db.String(100))  # Added batch_label field for grouping
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=True)  # Added company_id field


class ProductHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    trxn_date = db.Column(db.DateTime, nullable=False)
    trxn_code = db.Column(db.String(20), nullable=False)  # 'TRANS IN' or 'TRANS OUT'
    payee = db.Column(db.String(200), nullable=False)  # purchase_order_place for TRANS IN, branch for TRANS OUT
    quantity_in = db.Column(db.Float, default=0.0)  # Quantity added
    quantity_out = db.Column(db.Float, default=0.0)  # Quantity removed
    net_change = db.Column(db.Float, nullable=False, default=0.0)  # Positive for TRANS IN, negative for TRANS OUT
    reference_id = db.Column(db.Integer)  # ID of the related batch or requisition
    reference_type = db.Column(db.String(50))  # 'batch' or 'requisition'
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Manila")))
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    
    product = db.relationship('Product', backref='history')


class ReceivingRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    requisition_item_id = db.Column(db.Integer, db.ForeignKey('requisition_item.id'), nullable=False)
    requisition_id = db.Column(db.Integer, db.ForeignKey('requisition.id'), nullable=False)
    released_qty = db.Column(db.Float, nullable=False, default=0.0)
    received_qty = db.Column(db.Float, nullable=False, default=0.0)
    variance_qty = db.Column(db.Float, nullable=False, default=0.0)
    variance_type = db.Column(db.String(20), default='exact')  # 'exact', 'over', 'short'
    confirmed_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    confirmed_at = db.Column(db.DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Manila")))
    notes = db.Column(db.Text)
    status = db.Column(db.String(30), default='approved')  # 'approved', 'pending_approval', 'resolved'
    resolution_type = db.Column(db.String(50), nullable=True)  # 'damaged_loss', 'warehouse_miscount_charge', 'store_wrong_count', 'restore_warehouse', 'restore_store', 'recount'
    admin_notes = db.Column(db.Text, nullable=True)
    resolved_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)

    requisition_item = db.relationship('RequisitionItem', backref='receiving_records')
    requisition = db.relationship('Requisition', backref='receiving_records')
    confirmed_by_user = db.relationship('User', foreign_keys=[confirmed_by], backref='receiving_records')
    resolved_by_user = db.relationship('User', foreign_keys=[resolved_by], backref='resolved_receiving_records')


class PendingRemoval(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    batch_id = db.Column(db.Integer, db.ForeignKey('warehouse_product_batch.id'), nullable=False)
    requested_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    reason = db.Column(db.String(200), nullable=False)
    remarks = db.Column(db.Text)
    status = db.Column(db.String(20), default='Pending')  # Pending, Approved, Rejected
    reviewed_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    review_remarks = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Manila")))
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    
    # Relationships
    product = db.relationship('Product', backref='pending_removals')
    batch = db.relationship('WarehouseProductBatch', backref='pending_removals')
    requester = db.relationship('User', foreign_keys=[requested_by], backref='pending_removals_requested')
    reviewer = db.relationship('User', foreign_keys=[reviewed_by], backref='pending_removals_reviewed')


class DeletionRequest(db.Model):
    """WH-Admin requests to delete a ProductHistory record; requires Company-Admin approval."""
    id = db.Column(db.Integer, primary_key=True)
    product_history_id = db.Column(db.Integer, db.ForeignKey('product_history.id', ondelete='SET NULL'), nullable=True)  # nullable: record is deleted after approval
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    trxn_code = db.Column(db.String(20), nullable=False)       # 'TRANS IN' or 'TRANS OUT'
    quantity_in = db.Column(db.Float, default=0.0)
    quantity_out = db.Column(db.Float, default=0.0)
    net_change = db.Column(db.Float, default=0.0)
    reason = db.Column(db.Text, nullable=False)                 # Why WH-Admin wants it deleted
    status = db.Column(db.String(20), default='Pending')       # Pending / Approved / Rejected
    requested_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    review_remarks = db.Column(db.Text)
    requested_at = db.Column(db.DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Manila")))
    reviewed_at = db.Column(db.DateTime, nullable=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)

    # Relationships
    product_history = db.relationship('ProductHistory', backref='deletion_requests')
    product = db.relationship('Product')
    requester = db.relationship('User', foreign_keys=[requested_by], backref='deletion_requests_made')
    reviewer = db.relationship('User', foreign_keys=[reviewed_by], backref='deletion_requests_reviewed')


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=True)
    type = db.Column(db.String(50), nullable=False, default='info')
    reference_type = db.Column(db.String(50), nullable=True)
    reference_id = db.Column(db.Integer, nullable=True)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Manila")))

    user = db.relationship('User', backref='notifications')


class Spoilage(db.Model):
    __tablename__ = 'spoilage'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    side = db.Column(db.String(20), nullable=False)  # 'warehouse' or 'store'
    quantity = db.Column(db.Float, nullable=False)
    exp_date = db.Column(db.Date, nullable=True)  # expiry date (if applicable)
    reason = db.Column(db.String(200), nullable=True)
    remarks = db.Column(db.Text, nullable=True)
    images = db.Column(db.Text, nullable=True)  # JSON-encoded list of image filenames
    declaration_date = db.Column(db.Date, nullable=True)  # date of declaration
    declared_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Manila")))

    # Relationships
    product = db.relationship('Product', backref=db.backref('spoilages', cascade="all, delete-orphan"))
    user = db.relationship('User', backref='declared_spoilages', foreign_keys=[declared_by])

    @property
    def image_list(self):
        if not self.images:
            return []
        try:
            parsed = json.loads(self.images)
            if isinstance(parsed, list):
                return parsed
            return [parsed]
        except Exception:
            return [s.strip() for s in self.images.split(',') if s.strip()]


class OnTheHouse(db.Model):
    """On The House (OTH) model for employee food and snacks privilege."""
    __tablename__ = 'on_the_house'

    id = db.Column(db.Integer, primary_key=True)
    transaction_date = db.Column(db.Date, nullable=False, default=lambda: datetime.now(ZoneInfo("Asia/Manila")).date())
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    employee_name = db.Column(db.String(150), nullable=False)  # Employee receiving the OTH
    purpose = db.Column(db.Text, nullable=False)  # Reason / purpose for the OTH
    intended_approver = db.Column(db.String(150), nullable=True)  # Optional intended approver noted by requester
    approver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Approver user ID
    approver_name = db.Column(db.String(150), nullable=True)  # Full name of the approver
    status = db.Column(db.String(50), default='Pending', nullable=False)  # 'Pending', 'Approved', 'Declined', 'Released'
    requested_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Manila")))
    date_approved = db.Column(db.DateTime, nullable=True)
    date_declined = db.Column(db.DateTime, nullable=True)
    date_released = db.Column(db.DateTime, nullable=True)
    released_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    admin_notes = db.Column(db.Text, nullable=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=True)

    # Relationships
    product = db.relationship('Product', backref=db.backref('oth_records', lazy='dynamic'))
    requester = db.relationship('User', foreign_keys=[requested_by], backref='requested_oth_records')
    approver = db.relationship('User', foreign_keys=[approver_id], backref='approved_oth_records')
    releaser = db.relationship('User', foreign_keys=[released_by], backref='released_oth_records')


class StoreProduction(db.Model):
    """Store-side production tracking where finished goods/portions deduct from store inventory."""
    __tablename__ = 'store_production'

    id = db.Column(db.Integer, primary_key=True)
    batch_code = db.Column(db.String(50), nullable=False)  # e.g., 'PRD-20260930-001'
    production_date = db.Column(db.Date, nullable=False, default=lambda: datetime.now(ZoneInfo("Asia/Manila")).date())
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    product_name = db.Column(db.String(100), nullable=False)
    portion_formula = db.Column(db.String(100), nullable=False)  # e.g., '1order=175grams', '1pc'
    quantity = db.Column(db.Float, nullable=False)  # Quantity produced in orders or pieces
    unit_type = db.Column(db.String(20), default='order')  # 'order' or 'piece'
    total_yield_grams = db.Column(db.Float, nullable=True)  # e.g. quantity * 175
    store_qty_before = db.Column(db.Float, nullable=False, default=0.0)
    store_qty_after = db.Column(db.Float, nullable=False, default=0.0)
    produced_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(ZoneInfo("Asia/Manila")))
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=True)

    # Relationships
    product = db.relationship('Product', backref=db.backref('store_productions', lazy='dynamic'))
    producer = db.relationship('User', foreign_keys=[produced_by], backref='store_productions')
