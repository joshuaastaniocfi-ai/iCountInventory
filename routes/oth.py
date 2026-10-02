from datetime import datetime, date
from zoneinfo import ZoneInfo
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import desc, or_

from extensions import db
from models import OnTheHouse, Product, WarehouseProductBatch, ProductHistory, User, Company
from helpers import admin_required, log_activity, create_notification

oth_bp = Blueprint('oth', __name__, url_prefix='/oth')


@oth_bp.route('/', methods=['GET', 'POST'])
@login_required
@admin_required
def oth_list():
    """Display list of On The House (OTH) requests and management dashboard."""
    # If a POST is sent to /oth/ or a GET with creation query parameters:
    if request.method == 'POST' or (request.args.get('product_id') and (request.args.get('employee_name') or request.args.get('quantity'))):
        return create_oth_request()

    # WH-Admin and SYS-Admin see records across all companies (warehouse-wide oversight)
    if current_user.role in ['SYS-Admin', 'WH-Admin']:
        company_id = None
    else:
        company_id = getattr(current_user, 'company_id', None)

    # Base query
    query = OnTheHouse.query
    if company_id:
        query = query.filter(or_(OnTheHouse.company_id == company_id, OnTheHouse.company_id.is_(None)))

    # Filtering parameters
    status_filter = request.args.get('status', 'all').strip()
    search = request.args.get('search', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()

    if status_filter and status_filter.lower() != 'all':
        query = query.filter(OnTheHouse.status.ilike(status_filter))

    if search:
        search_term = f"%{search}%"
        query = query.join(Product).filter(
            or_(
                OnTheHouse.employee_name.ilike(search_term),
                OnTheHouse.purpose.ilike(search_term),
                OnTheHouse.approver_name.ilike(search_term),
                Product.name.ilike(search_term),
                Product.barcode.ilike(search_term)
            )
        )

    if start_date:
        try:
            s_date = datetime.strptime(start_date, '%Y-%m-%d').date()
            query = query.filter(OnTheHouse.transaction_date >= s_date)
        except ValueError:
            pass

    if end_date:
        try:
            e_date = datetime.strptime(end_date, '%Y-%m-%d').date()
            query = query.filter(OnTheHouse.transaction_date <= e_date)
        except ValueError:
            pass

    records = query.order_by(desc(OnTheHouse.id)).all()

    # KPI counts (unfiltered by status/search for the company)
    base_company_query = OnTheHouse.query
    if company_id:
        base_company_query = base_company_query.filter(or_(OnTheHouse.company_id == company_id, OnTheHouse.company_id.is_(None)))

    total_count = base_company_query.count()
    pending_count = base_company_query.filter(OnTheHouse.status == 'Pending').count()
    approved_count = base_company_query.filter(OnTheHouse.status == 'Approved').count()
    released_count = base_company_query.filter(OnTheHouse.status == 'Released').count()
    declined_count = base_company_query.filter(OnTheHouse.status == 'Declined').count()

    # Get available warehouse products for new request modal
    prod_query = Product.query
    if company_id:
        prod_query = prod_query.filter(or_(Product.company_id == company_id, Product.company_id.is_(None)))
    available_products = prod_query.order_by(Product.name.asc()).all()

    # Get potential approvers (Company-Admin and SYS-Admin for this company)
    approver_query = User.query.filter(User.role.in_(['Company-Admin', 'SYS-Admin']))
    if company_id:
        approver_query = approver_query.filter(
            or_(User.company_id == company_id, User.company_id.is_(None))
        )
    potential_approvers = approver_query.order_by(User.full_name.asc()).all()

    now_manila = datetime.now(ZoneInfo("Asia/Manila"))
    today_str = now_manila.strftime('%Y-%m-%d')

    return render_template(
        'warehouse/oth_list.html',
        records=records,
        total_count=total_count,
        pending_count=pending_count,
        approved_count=approved_count,
        released_count=released_count,
        declined_count=declined_count,
        available_products=available_products,
        potential_approvers=potential_approvers,
        status_filter=status_filter,
        search=search,
        start_date=start_date,
        end_date=end_date,
        today_str=today_str,
        now=now_manila
    )


@oth_bp.route('/request', methods=['GET', 'POST'])
@login_required
@admin_required
def create_oth_request():
    """Create a new On The House (OTH) request (Warehouse Admin / SYS-Admin / Company-Admin)."""
    if current_user.role not in ['WH-Admin', 'SYS-Admin', 'Company-Admin']:
        if request.is_json:
            return jsonify({'success': False, 'message': 'Only Admins can create OTH requests.'}), 403
        flash('Only Admins can create OTH requests.', 'danger')
        return redirect(url_for('oth.oth_list'))

    # Extract data from JSON, form, or query parameters
    if request.is_json:
        data = request.get_json(silent=True) or {}
    elif request.form:
        data = request.form
    else:
        data = request.args

    tx_date_raw = data.get('transaction_date')
    product_id = data.get('product_id')
    quantity_raw = data.get('quantity')
    employee_name = (data.get('employee_name') or '').strip()
    purpose = (data.get('purpose') or '').strip()

    # Basic validations
    if not product_id or not quantity_raw or not employee_name or not purpose:
        msg = 'Product, quantity, employee name, and purpose are required.'
        if request.is_json:
            return jsonify({'success': False, 'message': msg}), 400
        flash(msg, 'danger')
        return redirect(url_for('oth.oth_list'))

    try:
        quantity = float(quantity_raw)
        if quantity <= 0:
            raise ValueError()
    except (ValueError, TypeError):
        msg = 'Quantity must be a positive number.'
        if request.is_json:
            return jsonify({'success': False, 'message': msg}), 400
        flash(msg, 'danger')
        return redirect(url_for('oth.oth_list'))

    try:
        product_id = int(product_id)
    except (ValueError, TypeError):
        msg = 'Invalid product selected.'
        if request.is_json:
            return jsonify({'success': False, 'message': msg}), 400
        flash(msg, 'danger')
        return redirect(url_for('oth.oth_list'))

    # Parse transaction date
    if tx_date_raw:
        try:
            tx_date = datetime.strptime(str(tx_date_raw).strip(), '%Y-%m-%d').date()
        except ValueError:
            tx_date = datetime.now(ZoneInfo("Asia/Manila")).date()
    else:
        tx_date = datetime.now(ZoneInfo("Asia/Manila")).date()

    # Find product
    product = Product.query.get(product_id)
    if not product:
        msg = 'Selected product does not exist.'
        if request.is_json:
            return jsonify({'success': False, 'message': msg}), 404
        flash(msg, 'danger')
        return redirect(url_for('oth.oth_list'))

    # Verify company only if not SYS-Admin / WH-Admin and product belongs to another company
    if current_user.role not in ['SYS-Admin', 'WH-Admin'] and current_user.company_id and product.company_id and product.company_id != current_user.company_id:
        msg = 'Product does not belong to your company.'
        if request.is_json:
            return jsonify({'success': False, 'message': msg}), 403
        flash(msg, 'danger')
        return redirect(url_for('oth.oth_list'))

    company_id = product.company_id or getattr(current_user, 'company_id', None)
    if not company_id:
        first_comp = Company.query.first()
        company_id = first_comp.id if first_comp else None

    # Create OTH Record
    now_ph = datetime.now(ZoneInfo("Asia/Manila"))
    oth_record = OnTheHouse(
        transaction_date=tx_date,
        product_id=product.id,
        quantity=quantity,
        employee_name=employee_name,
        purpose=purpose,
        intended_approver=None,
        status='Pending',
        requested_by=current_user.id,
        created_at=now_ph,
        company_id=company_id
    )

    try:
        db.session.add(oth_record)
        db.session.commit()
    except Exception as commit_err:
        db.session.rollback()
        msg = f'Failed to save OTH request: {str(commit_err)}'
        if request.is_json:
            return jsonify({'success': False, 'message': msg}), 500
        flash(msg, 'danger')
        return redirect(url_for('oth.oth_list'))

    # Notify Company Admins and System Admins
    comp_admins = User.query.filter(
        User.role.in_(['Company-Admin', 'SYS-Admin'])
    )
    if company_id:
        comp_admins = comp_admins.filter(or_(User.company_id == company_id, User.company_id.is_(None)))
    comp_admins = comp_admins.all()

    for ca in comp_admins:
        try:
            create_notification(
                user_id=ca.id,
                title="New OTH Request for Approval",
                message=f"{current_user.full_name or current_user.username} submitted an OTH request for {employee_name} ({quantity} {product.uom or 'unit'} of {product.name}).",
                type='info',
                reference_type='oth',
                reference_id=oth_record.id
            )
        except Exception:
            pass

    try:
        log_activity(
            action="OTH Requested",
            details=f"Created OTH Request #{oth_record.id} for employee <strong>{employee_name}</strong>: {quantity} {product.uom or 'unit'} of {product.name} ({purpose})."
        )
    except Exception:
        pass

    success_msg = f"OTH request for {employee_name} submitted successfully! Awaiting Company Admin or System Admin approval."
    if request.is_json:
        return jsonify({'success': True, 'message': success_msg, 'oth_id': oth_record.id})
    flash(success_msg, 'success')
    return redirect(url_for('oth.oth_list'))


@oth_bp.route('/<int:oth_id>/approve', methods=['POST'])
@login_required
@admin_required
def approve_oth(oth_id):
    """Approve an OTH request (Company Admin / SYS-Admin)."""
    if current_user.role not in ['Company-Admin', 'SYS-Admin']:
        return jsonify({'success': False, 'message': 'Only Company Admin or System Admin can approve OTH requests.'}), 403

    oth = OnTheHouse.query.get_or_404(oth_id)

    if oth.status != 'Pending':
        return jsonify({'success': False, 'message': f'Request cannot be approved because current status is {oth.status}.'}), 400

    # Ensure company matches if not sys-admin
    if current_user.role != 'SYS-Admin' and current_user.company_id and oth.company_id and oth.company_id != current_user.company_id:
        return jsonify({'success': False, 'message': 'Access denied to this company record.'}), 403

    data = request.get_json() if request.is_json else request.form
    approver_name = (data.get('approver_name') or current_user.full_name or current_user.username).strip()
    admin_notes = (data.get('admin_notes') or '').strip()

    now_ph = datetime.now(ZoneInfo("Asia/Manila"))
    oth.status = 'Approved'
    oth.approver_id = current_user.id
    oth.approver_name = approver_name
    oth.date_approved = now_ph
    if admin_notes:
        oth.admin_notes = admin_notes

    db.session.commit()

    # Notify Requester (WH-Admin)
    if oth.requested_by:
        try:
            create_notification(
                user_id=oth.requested_by,
                title="OTH Request Approved",
                message=f"Your OTH request #{oth.id} for {oth.employee_name} was approved by {approver_name}. You may now release the items.",
                type='success',
                reference_type='oth',
                reference_id=oth.id
            )
        except Exception:
            pass

    log_activity(
        action="OTH Approved",
        details=f"Approved OTH Request #{oth.id} for employee <strong>{oth.employee_name}</strong> by {approver_name}."
    )

    return jsonify({
        'success': True,
        'message': f'OTH request #{oth.id} approved successfully! Warehouse Admin can now release the items.',
        'approver_name': approver_name,
        'status': 'Approved'
    })


@oth_bp.route('/<int:oth_id>/decline', methods=['POST'])
@login_required
@admin_required
def decline_oth(oth_id):
    """Decline an OTH request (Company Admin / SYS-Admin). Once declined, no release button exists."""
    if current_user.role not in ['Company-Admin', 'SYS-Admin']:
        return jsonify({'success': False, 'message': 'Only Company Admin or System Admin can decline OTH requests.'}), 403

    oth = OnTheHouse.query.get_or_404(oth_id)

    if oth.status != 'Pending':
        return jsonify({'success': False, 'message': f'Request cannot be declined because current status is {oth.status}.'}), 400

    if current_user.role != 'SYS-Admin' and current_user.company_id and oth.company_id and oth.company_id != current_user.company_id:
        return jsonify({'success': False, 'message': 'Access denied to this company record.'}), 403

    data = request.get_json() if request.is_json else request.form
    reason = (data.get('reason') or data.get('admin_notes') or '').strip()
    if not reason:
        return jsonify({'success': False, 'message': 'A reason is required to decline the request.'}), 400

    approver_name = (data.get('approver_name') or current_user.full_name or current_user.username).strip()

    now_ph = datetime.now(ZoneInfo("Asia/Manila"))
    oth.status = 'Declined'
    oth.approver_id = current_user.id
    oth.approver_name = approver_name
    oth.date_declined = now_ph
    oth.admin_notes = reason

    db.session.commit()

    # Notify Requester
    if oth.requested_by:
        try:
            create_notification(
                user_id=oth.requested_by,
                title="OTH Request Declined",
                message=f"Your OTH request #{oth.id} for {oth.employee_name} was declined by {approver_name}. Reason: {reason}",
                type='danger',
                reference_type='oth',
                reference_id=oth.id
            )
        except Exception:
            pass

    log_activity(
        action="OTH Declined",
        details=f"Declined OTH Request #{oth.id} for employee <strong>{oth.employee_name}</strong> by {approver_name}. Reason: {reason}"
    )

    return jsonify({
        'success': True,
        'message': f'OTH request #{oth.id} has been declined.',
        'approver_name': approver_name,
        'status': 'Declined'
    })


@oth_bp.route('/<int:oth_id>/release', methods=['POST'])
@login_required
@admin_required
def release_oth(oth_id):
    """
    Set an approved OTH request as Released (Warehouse Admin / SYS-Admin).
    Deducts the quantity from warehouse quantity and FIFO batches, and writes to ProductHistory.
    """
    if current_user.role not in ['WH-Admin', 'SYS-Admin', 'Company-Admin']:
        return jsonify({'success': False, 'message': 'Only Warehouse Admin or Company Admin can release OTH stock.'}), 403

    oth = OnTheHouse.query.get_or_404(oth_id)

    if oth.status != 'Approved':
        return jsonify({'success': False, 'message': f'Cannot release items. Current request status is "{oth.status}". Only "Approved" requests can be released.'}), 400

    product = Product.query.get(oth.product_id)
    if not product:
        return jsonify({'success': False, 'message': 'Product associated with this request was not found.'}), 404

    # Check sufficient stock
    avail_qty = float(product.warehouse_qty or 0.0)
    if avail_qty < oth.quantity:
        return jsonify({
            'success': False,
            'message': f'Cannot release! Insufficient warehouse stock. Available: {avail_qty} {product.uom}, Needed: {oth.quantity} {product.uom}.'
        }), 400

    now_ph = datetime.now(ZoneInfo("Asia/Manila"))

    # 1. Deduct from warehouse_qty and total quantity
    product.warehouse_qty = max(0.0, avail_qty - oth.quantity)
    product.quantity = product.warehouse_qty + float(product.store_qty or 0.0)
    product.last_updated = now_ph

    # 2. Deduct from WarehouseProductBatch FIFO (earliest expiry first)
    remaining_to_deduct = oth.quantity
    batches = (WarehouseProductBatch.query
               .filter_by(product_id=product.id)
               .filter(WarehouseProductBatch.quantity > 0)
               .order_by(WarehouseProductBatch.exp_date.asc())
               .all())

    for b in batches:
        if remaining_to_deduct <= 0:
            break
        deduct_amt = min(b.quantity, remaining_to_deduct)
        b.quantity -= deduct_amt
        remaining_to_deduct -= deduct_amt

    # 3. Create ProductHistory record (TRANS OUT)
    history_record = ProductHistory(
        product_id=product.id,
        trxn_date=now_ph,
        trxn_code='TRANS OUT',
        payee=f"OTH - {oth.employee_name} ({oth.purpose})",
        quantity_in=0.0,
        quantity_out=oth.quantity,
        net_change=-oth.quantity,
        reference_id=oth.id,
        reference_type='oth',
        created_at=now_ph,
        company_id=oth.company_id
    )
    db.session.add(history_record)

    # 4. Update OTH request status
    oth.status = 'Released'
    oth.released_by = current_user.id
    oth.date_released = now_ph

    db.session.commit()

    # 5. Log activity
    log_activity(
        action="OTH Released",
        details=(
            f"Released OTH #{oth.id} for employee <strong>{oth.employee_name}</strong>: "
            f"<strong>{oth.quantity} {product.uom}</strong> of <strong>{product.name}</strong> "
            f"deducted from warehouse inventory (Remaining warehouse stock: {product.warehouse_qty} {product.uom})."
        )
    )

    return jsonify({
        'success': True,
        'message': f'Successfully released {oth.quantity} {product.uom} of {product.name} to {oth.employee_name}. Warehouse inventory updated!',
        'status': 'Released',
        'remaining_warehouse_qty': product.warehouse_qty
    })


@oth_bp.route('/<int:oth_id>/slip')
@login_required
@admin_required
def oth_slip(oth_id):
    """Render printable or modal view of the OTH transaction slip."""
    oth = OnTheHouse.query.get_or_404(oth_id)
    if current_user.role not in ['SYS-Admin', 'WH-Admin'] and current_user.company_id and oth.company_id and oth.company_id != current_user.company_id:
        flash('Access denied.', 'danger')
        return redirect(url_for('oth.oth_list'))

    company = Company.query.get(oth.company_id) if oth.company_id else None
    return render_template('warehouse/oth_slip.html', oth=oth, company=company)


@oth_bp.route('/api/warehouse-products')
@login_required
@admin_required
def api_warehouse_products():
    """API endpoint to get warehouse products with available stock for dropdowns."""
    company_id = current_user.company_id if current_user.role != 'SYS-Admin' else None
    query = Product.query
    if company_id:
        query = query.filter(Product.company_id == company_id)

    products = query.filter(Product.warehouse_qty > 0).order_by(Product.name.asc()).all()
    results = [
        {
            'id': p.id,
            'name': p.name,
            'barcode': p.barcode or '',
            'warehouse_qty': float(p.warehouse_qty or 0.0),
            'uom': p.uom or 'unit',
            'category': p.category or ''
        }
        for p in products
    ]
    return jsonify({'success': True, 'products': results})
