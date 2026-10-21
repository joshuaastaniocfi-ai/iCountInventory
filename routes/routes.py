"""
receiving.py — Blueprint for receiving/delivery confirmation
Handles listing requisitions awaiting delivery and confirming actual received quantities
with variance tracking.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user

from extensions import db
from models import (
    Requisition, RequisitionItem, RequisitionBatchDeduction,
    Product, WarehouseProductBatch, StoreProductBatch, ProductHistory, ReceivingRecord, ActivityLog, User
)

receiving_bp = Blueprint('receiving', __name__, url_prefix='/receiving')

PH_TZ = ZoneInfo("Asia/Manila")


def _company_guard(requisition):
    """Return True if current user may access this requisition."""
    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        return True
    return requisition.company_id == current_user.company_id or getattr(requisition, 'destination_company_id', None) == current_user.company_id



# ─────────────────────────────────────────────────
#  API LIST — JSON: requisitions ready for receiving
# ─────────────────────────────────────────────────
@receiving_bp.route('/api/list')
@login_required
def api_list_receiving():
    status_filter = request.args.get('status', 'all').lower()
    search_q = request.args.get('q', '').strip().lower()

    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        query = Requisition.query
    else:
        query = Requisition.query.filter(
            (Requisition.company_id == current_user.company_id) |
            (Requisition.destination_company_id == current_user.company_id)
        )

    # Show approved, dispatched, delivered, partial, and discrepancy requisitions
    valid_statuses = [
        'approved', 'Approved', 'Dispatched', 'dispatched',
        'Delivered', 'delivered', 'Partial', 'partial',
        'Discrepancy - Pending Approval', 'Variance - Pending Approval'
    ]
    query = query.filter(Requisition.status.in_(valid_statuses))

    if status_filter != 'all':
        if status_filter == 'pending':
            query = query.filter(Requisition.status.in_(['approved', 'Approved', 'Dispatched', 'dispatched', 'Discrepancy - Pending Approval', 'Variance - Pending Approval']))
        elif status_filter == 'delivered':
            query = query.filter(Requisition.status.in_(['Delivered', 'delivered']))
        elif status_filter == 'partial':
            query = query.filter(Requisition.status.in_(['Partial', 'partial']))
        elif status_filter == 'discrepancy':
            query = query.filter(Requisition.status.in_(['Discrepancy - Pending Approval', 'Variance - Pending Approval']))

    requisitions = query.order_by(Requisition.date_created.desc()).all()

    if search_q:
        def matches(r):
            ref = (f"REQ-{r.date_created.year}-{r.id:04d}" if r.date_created else f"REQ-{r.id:04d}").lower()
            if search_q in ref or search_q in str(r.id).lower():
                return True
            return any(search_q in (item.product.name.lower() if item.product else '') for item in r.items)
        requisitions = [r for r in requisitions if matches(r)]

    rows = []
    for r in requisitions:
        ref = f"REQ-{r.date_created.year}-{r.id:04d}" if r.date_created else f"REQ-{r.id:04d}"

        # Determine item statuses from receiving records
        all_delivered = True
        any_received = False
        for item in r.items:
            records = ReceivingRecord.query.filter_by(requisition_item_id=item.id).all()
            if records:
                total_received = sum((rec.received_qty or 0.0) for rec in records)
                if total_received > 0:
                    any_received = True
                target_qty = item.released_quantity if item.released_quantity is not None else item.quantity
                if total_received < target_qty:
                    all_delivered = False
            else:
                all_delivered = False

        if r.status in ('Discrepancy - Pending Approval', 'Variance - Pending Approval'):
            display_status = 'Discrepancy - Pending Approval'
        elif r.status in ('Delivered', 'delivered') or (all_delivered and r.items and any_received):
            display_status = 'Delivered'
        elif any_received:
            display_status = 'Partial'
        else:
            display_status = 'Pending'

        items_data = [{
            'id': item.id,
            'product_id': item.product_id,
            'name': item.product.name if item.product else 'Unknown',
            'req_qty': item.quantity,
            'uom': item.uom,
            'is_optional': getattr(item, 'is_optional', False),
            'item_status': _get_item_status(item)
        } for item in r.items]

        rows.append({
            'id': r.id,
            'ref': ref,
            'status': display_status,
            'db_status': r.status,
            'has_discrepancy': r.status == 'Discrepancy - Pending Approval',
            'can_resolve': current_user.role in ['Company-Admin', 'SYS-Admin'] and r.status == 'Discrepancy - Pending Approval',
            'is_company_admin': current_user.role in ['Company-Admin', 'SYS-Admin'],
            'urgency': getattr(r, 'urgency', 'normal'),
            'date_created': r.date_created.strftime('%b %d, %Y'),
            'date_approved': r.date_approved.strftime('%b %d, %Y') if r.date_approved else None,
            'date_of_delivery': r.date_of_delivery.strftime('%b %d, %Y %I:%M %p') if r.date_of_delivery else None,
            'requested_by': r.requested_by,
            'branch': r.branch,
            'item_count': len(r.items),
            'items': items_data,
        })

    return jsonify({'success': True, 'rows': rows})


def _get_item_status(item):
    records = ReceivingRecord.query.filter_by(requisition_item_id=item.id).all()
    if not records:
        return 'Pending'
    total_received = sum(rec.received_qty for rec in records)
    if total_received >= item.quantity:
        return 'Delivered'
    if total_received > 0:
        return 'Partial'
    return 'Pending'


# ─────────────────────────────────────────────────
#  API DETAIL — JSON: single requisition with items
# ─────────────────────────────────────────────────
@receiving_bp.route('/api/detail/<int:req_id>')
@login_required
def api_receiving_detail(req_id):
    req = Requisition.query.get_or_404(req_id)
    if not _company_guard(req):
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    ref = f"REQ-{req.date_created.year}-{req.id:04d}"

    items = []
    for item in req.items:
        if getattr(item, 'is_optional', False):
            continue  # handled separately below
        product = item.product

        existing = ReceivingRecord.query.filter_by(
            requisition_item_id=item.id,
            requisition_id=req.id
        ).first()

        # Expected quantity is what was released by the warehouse for delivery, not the store's original request
        warehouse_released = existing.released_qty if (existing and existing.released_qty is not None) else (item.released_quantity if item.released_quantity is not None else item.quantity)


        items.append({
            'item_id': item.id,
            'product_id': product.id if product else None,
            'product_name': product.name if product else 'Unknown',
            'uom': item.uom,
            'requested_qty': item.quantity,
            'warehouse_released': warehouse_released,
            'warehouse_stock': product.quantity if product else 0,
            'received_qty': existing.received_qty if existing and existing.status != 'pending' else None,
            'variance_qty': existing.variance_qty if existing and existing.status != 'pending' else None,
            'variance_type': existing.variance_type if existing and existing.status != 'pending' else None,
            'status': existing.status if existing else 'pending',
            'resolution_type': existing.resolution_type if existing else None,
            'admin_notes': existing.admin_notes if existing else None,
        })

    # Also fetch optional items added to this delivery
    optional_items = RequisitionItem.query.filter_by(
        requisition_id=req.id,
        is_optional=True
    ).all()

    for opt in optional_items:
        product = opt.product
        existing = ReceivingRecord.query.filter_by(
            requisition_item_id=opt.id,
            requisition_id=req.id
        ).first()
        items.append({
            'item_id': opt.id,
            'product_id': product.id if product else None,
            'product_name': product.name if product else 'Unknown',
            'uom': opt.uom,
            'warehouse_released': existing.released_qty if existing else opt.quantity,
            'warehouse_stock': product.quantity if product else 0,
            'received_qty': existing.received_qty if existing else None,
            'variance_qty': existing.variance_qty if existing else None,
            'variance_type': existing.variance_type if existing else None,
            'status': existing.status if existing else 'pending',
            'resolution_type': existing.resolution_type if existing else None,
            'admin_notes': existing.admin_notes if existing else None,
            'is_optional': True,
        })

    return jsonify({
        'success': True,
        'requisition': {
            'id': req.id,
            'ref': ref,
            'status': req.status,
            'can_resolve': current_user.role in ['Company-Admin', 'SYS-Admin'] and req.status == 'Discrepancy - Pending Approval',
            'is_company_admin': current_user.role in ['Company-Admin', 'SYS-Admin'],
            'date_created': req.date_created.strftime('%b %d, %Y'),
            'requested_by': req.requested_by,
            'branch': req.branch,
            'items': items
        }
    })


# ─────────────────────────────────────────────────
#  CONFIRM — POST: save actual received quantities
# ─────────────────────────────────────────────────
@receiving_bp.route('/api/confirm/<int:req_id>', methods=['POST'])
@login_required
def api_confirm_receiving(req_id):
    req = Requisition.query.get_or_404(req_id)
    if not _company_guard(req):
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    if req.status.lower() == 'delivered':
        return jsonify({'success': False, 'message': 'Already fully received.'}), 400

    data = request.get_json(silent=True) or request.form
    now = datetime.now(PH_TZ)
    req_ref = f"REQ-{req.date_created.year}-{req.id:04d}"
    errors = []
    any_received = False
    all_delivered = True
    processed_item_ids = set()

    # ── Process all items (both requested and previously-added optional) ──
    for item in req.items:
        processed_item_ids.add(item.id)

        actual_key = f'actual_{item.id}'
        released_key = f'released_{item.id}'

        # Read actual (received) qty
        raw_actual = data.get(actual_key, '').strip() if isinstance(data, dict) else request.form.get(actual_key, '').strip()

        if not raw_actual:
            all_delivered = False
            continue

        try:
            actual_qty = float(raw_actual)
        except ValueError:
            errors.append(f'Invalid received quantity for {item.product.name}')
            continue

        if actual_qty < 0:
            errors.append(f'Received quantity cannot be negative for {item.product.name}')
            continue

        if actual_qty > 0:
            any_received = True

        # Query existing record
        existing_record = ReceivingRecord.query.filter_by(requisition_item_id=item.id, requisition_id=req.id).first()

        # Read warehouse-released qty (what was declared/released by the warehouse)
        raw_released = data.get(released_key, '').strip() if isinstance(data, dict) else request.form.get(released_key, '').strip()
        if raw_released:
            try:
                warehouse_released = float(raw_released)
            except ValueError:
                errors.append(f'Invalid released quantity for {item.product.name}')
                continue
        else:
            warehouse_released = existing_record.released_qty if (existing_record and existing_record.released_qty is not None) else (item.released_quantity if item.released_quantity is not None else item.quantity)


        variance_qty = actual_qty - warehouse_released
        if variance_qty > 0:
            variance_type = 'over'
        elif variance_qty < 0:
            variance_type = 'short'
        else:
            variance_type = 'exact'

        # Determine item status
        if variance_qty == 0:
            rec_status = 'approved'
            rec_res_type = 'exact'
        else:
            rec_status = 'pending_approval'
            rec_res_type = None

        if existing_record:
            existing_record.released_qty = warehouse_released
            existing_record.received_qty = actual_qty
            existing_record.variance_qty = variance_qty
            existing_record.variance_type = variance_type
            existing_record.confirmed_by = current_user.id
            existing_record.confirmed_at = now
            existing_record.status = rec_status
            existing_record.resolution_type = rec_res_type
        else:
            record = ReceivingRecord(
                requisition_item_id=item.id,
                requisition_id=req.id,
                released_qty=warehouse_released,
                received_qty=actual_qty,
                variance_qty=variance_qty,
                variance_type=variance_type,
                confirmed_by=current_user.id,
                confirmed_at=now,
                status=rec_status,
                resolution_type=rec_res_type,
                company_id=current_user.company_id,
            )
            db.session.add(record)

        # ProductHistory entry for actual received goods
        history = ProductHistory(
            product_id=item.product_id,
            trxn_date=now,
            trxn_code='RECV IN',
            payee=req.branch or req.requested_by,
            quantity_in=actual_qty,
            quantity_out=0.0,
            net_change=actual_qty,
            reference_id=req.id,
            reference_type='receiving',
            company_id=current_user.company_id,
        )
        db.session.add(history)

        # Handle SHORT / OVER: store gets adjusted to physical count;
        # warehouse stock remains decremented and variance is quarantined awaiting Admin approval!
        if variance_type == 'short':
            shortage_qty = abs(variance_qty)
            product = item.product
            if product:
                product.store_qty -= shortage_qty
                if product.store_qty < 0:
                    product.store_qty = 0
                product.quantity = product.warehouse_qty + product.store_qty

        elif variance_type == 'over':
            over_qty = abs(variance_qty)
            product = item.product
            if product:
                product.store_qty += over_qty
                product.quantity = product.warehouse_qty + product.store_qty

        if actual_qty < warehouse_released:
            all_delivered = False
        elif actual_qty > warehouse_released:
            all_delivered = False

    # ── Process optional (added) items ──
    opt_idx = 0
    while True:
        pid_key = f'opt_product_id_{opt_idx}'
        rel_key = f'opt_released_{opt_idx}'
        recv_key = f'opt_received_{opt_idx}'

        raw_pid = data.get(pid_key, '').strip() if isinstance(data, dict) else request.form.get(pid_key, '').strip()
        if not raw_pid:
            break

        try:
            product_id = int(raw_pid)
        except (ValueError, TypeError):
            errors.append(f'Invalid product for optional item #{opt_idx + 1}')
            opt_idx += 1
            continue

        raw_released = data.get(rel_key, '').strip() if isinstance(data, dict) else request.form.get(rel_key, '').strip()
        raw_received = data.get(recv_key, '').strip() if isinstance(data, dict) else request.form.get(recv_key, '').strip()

        if not raw_released and not raw_received:
            opt_idx += 1
            continue

        try:
            released_qty = float(raw_released) if raw_released else 0
        except ValueError:
            errors.append(f'Invalid released qty for optional item #{opt_idx + 1}')
            opt_idx += 1
            continue

        try:
            received_qty = float(raw_received) if raw_received else 0
        except ValueError:
            errors.append(f'Invalid received qty for optional item #{opt_idx + 1}')
            opt_idx += 1
            continue

        if released_qty > 0:
            any_received = True

        # Look up product
        product = Product.query.get(product_id)
        if not product:
            errors.append(f'Product #{product_id} not found for optional item')
            opt_idx += 1
            continue

        # Check if optional item already exists for this product + requisition
        existing_opt_item = RequisitionItem.query.filter_by(
            requisition_id=req.id,
            product_id=product_id,
            is_optional=True
        ).first()

        if existing_opt_item:
            opt_item = existing_opt_item
            opt_item.quantity = released_qty
        else:
            opt_item = RequisitionItem(
                requisition_id=req.id,
                product_id=product_id,
                quantity=released_qty,
                uom=product.uom,
                is_optional=True,
            )
            db.session.add(opt_item)
            db.session.flush()

        # Deduct released qty from warehouse stock and credit store (only on first save)
        if not existing_opt_item:
            product.warehouse_qty -= released_qty
            if product.warehouse_qty < 0:
                product.warehouse_qty = 0
            product.store_qty += received_qty
            product.quantity = product.warehouse_qty + product.store_qty

            wh_history = ProductHistory(
                product_id=product_id,
                trxn_date=now,
                trxn_code='TRANS OUT',
                payee=f"OPTIONAL-{req_ref}",
                quantity_in=0.0,
                quantity_out=released_qty,
                net_change=-released_qty,
                reference_id=req.id,
                reference_type='receiving_optional',
                company_id=current_user.company_id,
            )
            db.session.add(wh_history)

        # Create / update receiving record for optional item
        var_qty = received_qty - released_qty
        var_type = 'exact'
        if var_qty > 0:
            var_type = 'over'
        elif var_qty < 0:
            var_type = 'short'

        existing_opt_rec = ReceivingRecord.query.filter_by(
            requisition_item_id=opt_item.id,
            requisition_id=req.id
        ).first()

        opt_rec_status = 'approved' if var_qty == 0 else 'pending_approval'
        opt_rec_res_type = 'exact' if var_qty == 0 else None

        if existing_opt_rec:
            existing_opt_rec.released_qty = released_qty
            existing_opt_rec.received_qty = received_qty
            existing_opt_rec.variance_qty = var_qty
            existing_opt_rec.variance_type = var_type
            existing_opt_rec.confirmed_by = current_user.id
            existing_opt_rec.confirmed_at = now
            existing_opt_rec.status = opt_rec_status
            existing_opt_rec.resolution_type = opt_rec_res_type
        else:
            rec = ReceivingRecord(
                requisition_item_id=opt_item.id,
                requisition_id=req.id,
                released_qty=released_qty,
                received_qty=received_qty,
                variance_qty=var_qty,
                variance_type=var_type,
                confirmed_by=current_user.id,
                confirmed_at=now,
                status=opt_rec_status,
                resolution_type=opt_rec_res_type,
                company_id=current_user.company_id,
            )
            db.session.add(rec)

        # Received history for optional item (RECV IN for the store)
        recv_history = ProductHistory(
            product_id=product_id,
            trxn_date=now,
            trxn_code='RECV IN',
            payee=req.branch or req.requested_by,
            quantity_in=received_qty,
            quantity_out=0.0,
            net_change=received_qty,
            reference_id=req.id,
            reference_type='receiving_optional',
            company_id=current_user.company_id,
        )
        db.session.add(recv_history)

        if received_qty < released_qty:
            all_delivered = False

        opt_idx += 1

    if errors:
        return jsonify({'success': False, 'message': '; '.join(errors)}), 400

    # Also consider optional items ready for delivery status
    if not any_received:
        req.status = 'approved'

    # ── Status determination & Discrepancy Detection ──
    # Check if any item had a variance against what was released by warehouse
    has_any_variance = False
    variance_items_summary = []
    for it in req.items:
        rec = ReceivingRecord.query.filter_by(requisition_item_id=it.id, requisition_id=req.id).first()
        if rec and rec.variance_type in ('short', 'over') and abs(rec.variance_qty) > 0:
            has_any_variance = True
            sign = '+' if rec.variance_qty > 0 else ''
            p_name = it.product.name if it.product else 'Item'
            variance_items_summary.append(f"{p_name}: Rel {rec.released_qty}, Recv {rec.received_qty} ({sign}{rec.variance_qty})")

    # Store variance directly in database linked to requisition ID
    req.has_variance = has_any_variance
    req.variance_summary = "; ".join(variance_items_summary) if has_any_variance else None

    if has_any_variance:
        req.status = 'Discrepancy - Pending Approval'
        # Automatically send notification to all Company-Admin and SYS-Admin users
        try:
            from helpers import create_notification
            admin_users = User.query.filter(
                User.role.in_(['Company-Admin', 'SYS-Admin'])
            ).filter(
                (User.company_id == req.company_id) | (User.company_id.is_(None))
            ).all()

            v_preview = "; ".join(variance_items_summary[:3])
            if len(variance_items_summary) > 3:
                v_preview += f" (+{len(variance_items_summary)-3} more)"

            for adm in admin_users:
                create_notification(
                    user_id=adm.id,
                    title=f"Delivery Variance Alert: {req_ref}",
                    message=f"Delivery variance declared on Requisition #{req.id} ({req.branch or req.requested_by}): {v_preview}. Admin investigation and declaration required.",
                    type="warning",
                    reference_type="delivery_variance",
                    reference_id=req.id
                )
        except Exception as notifErr:
            print(f"Discrepancy notification error: {notifErr}")
    elif all_delivered:
        req.status = 'Delivered'
    elif any_received:
        req.status = 'Partial'

    req.date_of_delivery = now

    # Activity log
    log = ActivityLog(
        action='Delivery Discrepancy Declared' if has_any_variance else 'Receiving confirmed',
        details=f'Requisition #{req_id} receiving {"declared with discrepancy (Pending Company-Admin Approval)" if has_any_variance else "confirmed"} by {current_user.full_name}',
        timestamp=now,
        company_id=current_user.company_id,
    )
    db.session.add(log)

    try:
        db.session.commit()
        return jsonify({
            'success': True,
            'message': 'Receiving recorded with discrepancy. Forwarded to Company-Admin for approval.' if has_any_variance else 'Receiving confirmed successfully.',
            'status': req.status,
            'has_discrepancy': has_any_variance
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'}), 500


# ─────────────────────────────────────────────────
#  HTML PAGES
# ─────────────────────────────────────────────────
@receiving_bp.route('/')
@login_required
def list_receiving():
    return redirect(url_for('receiving.deliveries_page'))


@receiving_bp.route('/<int:req_id>')
@login_required
def receiving_detail(req_id):
    req = Requisition.query.get_or_404(req_id)
    if not _company_guard(req):
        flash('Access denied.', 'danger')
        return redirect(url_for('receiving.deliveries_page'))

    ref = f"REQ-{req.date_created.year}-{req.id:04d}" if req.date_created else f"REQ-{req.id:04d}"

    items = []
    total_requested = 0
    total_released = 0
    total_received = 0
    total_variance = 0
    has_variance = False

    for item in req.items:
        product = item.product
        existing = ReceivingRecord.query.filter_by(
            requisition_item_id=item.id,
            requisition_id=req.id
        ).first()
        warehouse_released = existing.released_qty if (existing and existing.released_qty is not None) else (item.released_quantity if item.released_quantity is not None else item.quantity)
        received = existing.received_qty if existing else 0.0
        variance = existing.variance_qty if existing else 0.0
        vtype = existing.variance_type if existing else 'exact'
        if vtype != 'exact':
            has_variance = True

        total_requested += (item.quantity or 0)
        total_released += (warehouse_released or 0)
        total_received += received
        total_variance += variance

        items.append({
            'item_id': item.id,
            'product_id': product.id if product else None,
            'product_name': product.name if product else 'Unknown',
            'uom': item.uom,
            'is_optional': getattr(item, 'is_optional', False),
            'requested_qty': item.quantity,
            'warehouse_released': warehouse_released,
            'warehouse_stock': product.quantity if product else 0,
            'received_qty': existing.received_qty if existing else None,
            'variance_qty': variance,
            'variance_type': vtype,
            'notes': existing.notes if existing else '',
        })

    can_receive = (req.status.lower() in ['approved', 'dispatched', 'partial']) and req.status not in ['Discrepancy - Pending Approval', 'Delivered', 'delivered']
    can_resolve = (current_user.role in ['Company-Admin', 'SYS-Admin']) and (req.status == 'Discrepancy - Pending Approval')

    return render_template(
        'receiving/detail.html',
        req=req,
        ref=ref,
        items=items,
        total_requested=total_requested,
        total_released=total_released,
        total_received=total_received,
        total_variance=total_variance,
        has_variance=has_variance or bool(req.has_variance),
        can_receive=can_receive,
        can_resolve=can_resolve,
    )


# ─────────────────────────────────────────────────
#  DELIVERIES PAGE — View all completed deliveries with variances
# ─────────────────────────────────────────────────
@receiving_bp.route('/deliveries')
@login_required
def deliveries_page():
    return render_template('receiving/deliveries.html')


@receiving_bp.route('/api/deliveries')
@login_required
def api_deliveries():
    from sqlalchemy import or_

    status_filter = request.args.get('status', 'all')
    search = request.args.get('q', '').strip()
    date_from = request.args.get('from', '')
    date_to = request.args.get('to', '')

    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        base = Requisition.query
        metrics_base = Requisition.query
    else:
        condition = (
            (Requisition.company_id == current_user.company_id) |
            (Requisition.destination_company_id == current_user.company_id)
        )
        base = Requisition.query.filter(condition)
        metrics_base = Requisition.query.filter(condition)

    # Compute global metric counts for receiving tab badges & KPIs
    all_inbound_count = metrics_base.filter(Requisition.status.in_(['approved', 'Approved', 'Dispatched', 'dispatched'])).count()
    all_delivered_count = metrics_base.filter(Requisition.status.in_(['Delivered', 'delivered'])).count()
    all_discrepancy_count = metrics_base.filter(Requisition.status.in_(['Discrepancy - Pending Approval', 'Variance - Pending Approval'])).count()
    all_total_count = metrics_base.filter(Requisition.status.in_([
        'approved', 'Approved', 'Dispatched', 'dispatched',
        'Delivered', 'delivered', 'Partial', 'partial',
        'Discrepancy - Pending Approval', 'Variance - Pending Approval'
    ])).count()

    valid_statuses = [
        'approved', 'Approved', 'Dispatched', 'dispatched',
        'Delivered', 'delivered', 'Partial', 'partial',
        'Discrepancy - Pending Approval', 'Variance - Pending Approval'
    ]
    base = base.filter(Requisition.status.in_(valid_statuses))

    if status_filter != 'all':
        if status_filter in ('inbound', 'pending'):
            base = base.filter(Requisition.status.in_(['approved', 'Approved', 'Dispatched', 'dispatched']))
        elif status_filter in ('delivered', 'Delivered'):
            base = base.filter(Requisition.status.in_(['Delivered', 'delivered']))
        elif status_filter in ('partial', 'Partial'):
            base = base.filter(Requisition.status.in_(['Partial', 'partial']))
        elif status_filter in ('discrepancy', 'Discrepancy - Pending Approval'):
            base = base.filter(Requisition.status.in_(['Discrepancy - Pending Approval', 'Variance - Pending Approval']))
        elif status_filter == 'variance':
            base = base.filter(
                (Requisition.status.in_(['Discrepancy - Pending Approval', 'Variance - Pending Approval'])) |
                (Requisition.has_variance == True)
            )
        else:
            base = base.filter(Requisition.status == status_filter)

    if search:
        search_pattern = f'%{search}%'
        base = base.filter(
            or_(
                Requisition.branch.ilike(search_pattern),
                Requisition.requested_by.ilike(search_pattern),
                Requisition.id.ilike(search_pattern),
                Requisition.items.any(RequisitionItem.product.has(Product.name.ilike(search_pattern)))
            )
        )

    if date_from:
        try:
            d_from = datetime.fromisoformat(date_from)
            base = base.filter(or_(Requisition.date_of_delivery >= d_from, Requisition.date_created >= d_from))
        except Exception:
            pass
    if date_to:
        try:
            d_to = datetime.fromisoformat(date_to) + timedelta(days=1)
            base = base.filter(or_(Requisition.date_of_delivery <= d_to, Requisition.date_created <= d_to))
        except Exception:
            pass

    requisitions = base.order_by(Requisition.id.desc()).all()

    rows = []
    for req in requisitions:
        items = []
        total_requested = 0
        total_released = 0
        total_received = 0
        total_variance = 0
        has_variance = False
        res_info = None

        for item in req.items:
            rec = ReceivingRecord.query.filter_by(
                requisition_item_id=item.id,
                requisition_id=req.id
            ).first()
            released = rec.released_qty if (rec and rec.released_qty is not None) else (item.released_quantity if item.released_quantity is not None else item.quantity)
            received = rec.received_qty if rec else 0
            variance = rec.variance_qty if rec else 0
            vtype = rec.variance_type if rec else 'exact'
            if vtype != 'exact':
                has_variance = True
            total_requested += (item.quantity or 0)
            total_released += (released or 0)
            total_received += received
            total_variance += variance

            if rec and (rec.resolution_type or rec.admin_notes) and not res_info:
                res_info = {
                    'resolution_type': rec.resolution_type,
                    'admin_notes': rec.admin_notes,
                    'resolved_at': rec.resolved_at.strftime('%Y-%m-%d %I:%M %p') if rec.resolved_at else '',
                    'resolved_by_name': rec.resolved_by_user.full_name if rec.resolved_by_user else 'Admin'
                }

            items.append({
                'id': item.id,
                'product_name': item.product.name if item.product else 'Unknown',
                'uom': item.uom,
                'requested': item.quantity,
                'released': released,
                'received': received,
                'variance': variance,
                'variance_type': vtype,
                'status': rec.status if rec else 'pending',
                'resolution_type': rec.resolution_type if rec else None,
                'admin_notes': rec.admin_notes if rec else None,
            })

        ref = f"REQ-{req.date_created.year}-{req.id:04d}" if req.date_created else f"REQ-{req.id}"
        has_pending = (req.status == 'Discrepancy - Pending Approval')
        is_inbound = req.status.lower() in ['approved', 'dispatched']
        can_receive = (req.status.lower() in ['approved', 'dispatched', 'partial']) and req.status not in ['Discrepancy - Pending Approval', 'Delivered', 'delivered']

        date_display = req.date_of_delivery.strftime('%b %d, %Y %I:%M %p') if req.date_of_delivery else (
            req.date_created.strftime('%b %d, %Y') if req.date_created else '—'
        )

        rows.append({
            'id': req.id,
            'ref': ref,
            'branch': req.branch or 'Main Branch',
            'requested_by': req.requested_by,
            'status': req.status,
            'is_inbound': is_inbound,
            'can_receive': can_receive,
            'date_created': req.date_created.strftime('%Y-%m-%d %I:%M %p') if req.date_created else '',
            'date_of_delivery': req.date_of_delivery.strftime('%Y-%m-%d %I:%M %p') if req.date_of_delivery else '',
            'date_display': date_display,
            'items': items,
            'total_requested': total_requested,
            'total_released': total_released,
            'total_received': total_received,
            'total_variance': total_variance,
            'has_variance': has_variance or bool(req.has_variance),
            'variance_summary': req.variance_summary,
            'item_count': len(items),
            'has_pending_discrepancy': has_pending,
            'can_resolve': (current_user.role in ['Company-Admin', 'SYS-Admin']) and has_pending,
            'is_company_admin': current_user.role in ['Company-Admin', 'SYS-Admin'],
            'resolution_info': res_info,
            'variance_resolution': req.variance_resolution,
            'variance_admin_notes': req.variance_admin_notes,
            'variance_resolved_at': req.variance_resolved_at.strftime('%Y-%m-%d %I:%M %p') if req.variance_resolved_at else '',
            'variance_resolved_by': req.variance_resolver.full_name if req.variance_resolver else None,
        })

    return jsonify({
        'success': True,
        'rows': rows,
        'counts': {
            'inbound': all_inbound_count,
            'delivered': all_delivered_count,
            'discrepancy': all_discrepancy_count,
            'total': all_total_count
        }
    })


# ─────────────────────────────────────────────────
#  RESOLVE DISCREPANCY / VARIANCE — Company-Admin Decision
# ─────────────────────────────────────────────────
@receiving_bp.route('/api/resolve_discrepancy/<int:req_id>', methods=['POST'])
@login_required
def api_resolve_discrepancy(req_id):
    """
    Company-Admin / SYS-Admin resolution for delivery discrepancies and variances.
    Supported declaration reasons:
      - 'damaged_loss' (or 'transit_loss'): Damaged / Loss in transit. Stock written off permanently.
      - 'warehouse_miscount_charge': Charge / Miscount from warehouse release. Warehouse stock restored & accountability logged.
      - 'store_wrong_count': Wrong count in store received. Store physical count corrected & updated.
      - 'restore_warehouse' (or 'warehouse_return'): Restored in warehouse. Returned/retained goods restored to warehouse stock & batches.
      - 'restore_store': Restored in store. Goods located/recovered at store. Store inventory updated.
      - 'recount': Declaration rejected. Re-opens delivery for physical recount by store.
    """
    if current_user.role not in ['Company-Admin', 'SYS-Admin']:
        return jsonify({'success': False, 'message': 'Permission denied. Only Company-Admin or SYS-Admin can resolve delivery variances.'}), 403

    req = Requisition.query.get_or_404(req_id)
    if not _company_guard(req):
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    if req.status not in ['Discrepancy - Pending Approval', 'Variance - Pending Approval']:
        return jsonify({'success': False, 'message': f'Requisition is not awaiting variance resolution (current status: {req.status}).'}), 400

    data = request.get_json(silent=True) or request.form or {}
    resolution_type = (data.get('resolution_type') or '').strip().lower()
    admin_notes = (data.get('admin_notes') or '').strip()

    # Aliases
    if resolution_type == 'transit_loss':
        resolution_type = 'damaged_loss'
    elif resolution_type == 'warehouse_return':
        resolution_type = 'restore_warehouse'

    valid_resolutions = [
        'damaged_loss',
        'delivery_transit_loss',
        'delivery_spoilage_delay',
        'warehouse_miscount_charge',
        'warehouse_over_dispatch',
        'warehouse_damaged_prep',
        'store_wrong_count',
        'store_damage_unloading',
        'store_missing_post_delivery',
        'restore_warehouse',
        'restore_store',
        'supplier_defect',
        'recount'
    ]
    if resolution_type not in valid_resolutions:
        return jsonify({'success': False, 'message': f'Invalid resolution type. Must be one of: {", ".join(valid_resolutions)}'}), 400

    now = datetime.now(PH_TZ)
    req_ref = f"REQ-{req.date_created.year}-{req.id:04d}" if req.date_created else f"REQ-{req.id}"

    records = ReceivingRecord.query.filter_by(requisition_id=req.id).all()
    if not records:
        return jsonify({'success': False, 'message': 'No receiving records found for this requisition.'}), 400

    try:
        if resolution_type in ('damaged_loss', 'delivery_transit_loss'):
            # Delivery Driver / Logistics Accountable: Goods damaged, broken, or lost in transit
            for rec in records:
                item = rec.requisition_item
                product = item.product if item else None
                if not product:
                    continue

                if rec.variance_qty and rec.variance_qty < 0:
                    shortage = abs(rec.variance_qty)
                    loss_hist = ProductHistory(
                        product_id=product.id,
                        trxn_date=now,
                        trxn_code='DELIVERY LOSS',
                        payee=f"DELIVERY TRANSIT LOSS ({req.branch or req.requested_by})",
                        quantity_in=0.0,
                        quantity_out=shortage,
                        net_change=-shortage,
                        reference_id=req.id,
                        reference_type='delivery_loss',
                        notes=f"Damaged/Loss in transit approved by {current_user.full_name}. Accountable: Delivery/Driver. Missing {shortage} {item.uom or ''}. Notes: {admin_notes}",
                        company_id=req.company_id,
                    )
                    db.session.add(loss_hist)

                rec.status = 'resolved'
                rec.resolution_type = resolution_type
                rec.admin_notes = admin_notes
                rec.resolved_by = current_user.id
                rec.resolved_at = now

            req.status = 'Delivered'
            req.variance_resolution = resolution_type
            req.variance_resolved_by = current_user.id
            req.variance_resolved_at = now
            req.variance_admin_notes = admin_notes

            db.session.add(ActivityLog(
                action='Variance Declared: Delivery Transit Loss',
                details=f"Admin {current_user.full_name} declared variance on {req_ref} as Delivery Transit Loss (Accountable: Delivery / Driver). Notes: {admin_notes}",
                timestamp=now,
                company_id=req.company_id
            ))

        elif resolution_type == 'delivery_spoilage_delay':
            # Delivery Driver / Logistics Accountable: Perishable goods spoiled due to vehicle delay or temperature failure
            for rec in records:
                item = rec.requisition_item
                product = item.product if item else None
                if not product:
                    continue

                if rec.variance_qty and rec.variance_qty < 0:
                    shortage = abs(rec.variance_qty)
                    spoil_hist = ProductHistory(
                        product_id=product.id,
                        trxn_date=now,
                        trxn_code='DELIVERY LOSS',
                        payee=f"DELIVERY SPOILAGE/DELAY ({req.branch or req.requested_by})",
                        quantity_in=0.0,
                        quantity_out=shortage,
                        net_change=-shortage,
                        reference_id=req.id,
                        reference_type='delivery_spoilage',
                        notes=f"Transit spoilage/temperature delay approved by {current_user.full_name}. Accountable: Delivery/Logistics. Spoiled {shortage} {item.uom or ''}. Notes: {admin_notes}",
                        company_id=req.company_id,
                    )
                    db.session.add(spoil_hist)

                rec.status = 'resolved'
                rec.resolution_type = resolution_type
                rec.admin_notes = admin_notes
                rec.resolved_by = current_user.id
                rec.resolved_at = now

            req.status = 'Delivered'
            req.variance_resolution = resolution_type
            req.variance_resolved_by = current_user.id
            req.variance_resolved_at = now
            req.variance_admin_notes = admin_notes

            db.session.add(ActivityLog(
                action='Variance Declared: Delivery Spoilage Delay',
                details=f"Admin {current_user.full_name} declared variance on {req_ref} as Delivery Spoilage / Delay (Accountable: Delivery / Driver). Notes: {admin_notes}",
                timestamp=now,
                company_id=req.company_id
            ))

        elif resolution_type == 'warehouse_miscount_charge':
            # Warehouse Accountable: Warehouse under-dispatched or made release picking error; charge to warehouse
            for rec in records:
                item = rec.requisition_item
                product = item.product if item else None
                if not product:
                    continue

                if rec.variance_qty and rec.variance_qty < 0:
                    shortage = abs(rec.variance_qty)
                    # Restore unpicked stock back to warehouse
                    product.warehouse_qty = (product.warehouse_qty or 0) + shortage
                    product.quantity = (product.warehouse_qty or 0) + (product.store_qty or 0)

                    wb = WarehouseProductBatch.query.filter_by(product_id=product.id).filter(WarehouseProductBatch.quantity > 0).order_by(WarehouseProductBatch.exp_date.asc()).first()
                    if wb:
                        wb.quantity += shortage
                    else:
                        any_wb = WarehouseProductBatch.query.filter_by(product_id=product.id).order_by(WarehouseProductBatch.added_on.desc()).first()
                        if any_wb:
                            any_wb.quantity += shortage

                    miscount_hist = ProductHistory(
                        product_id=product.id,
                        trxn_date=now,
                        trxn_code='WH MISCOUNT',
                        payee=f"WAREHOUSE MISCOUNT/CHARGE ({req.branch or req.requested_by})",
                        quantity_in=shortage,
                        quantity_out=0.0,
                        net_change=shortage,
                        reference_id=req.id,
                        reference_type='warehouse_miscount_charge',
                        notes=f"Warehouse release miscount/charge logged by {current_user.full_name}. Accountable: Warehouse. Restored {shortage} {item.uom or ''} to warehouse stock. Notes: {admin_notes}",
                        company_id=req.company_id,
                    )
                    db.session.add(miscount_hist)

                rec.status = 'resolved'
                rec.resolution_type = 'warehouse_miscount_charge'
                rec.admin_notes = admin_notes
                rec.resolved_by = current_user.id
                rec.resolved_at = now

            req.status = 'Delivered'
            req.variance_resolution = 'warehouse_miscount_charge'
            req.variance_resolved_by = current_user.id
            req.variance_resolved_at = now
            req.variance_admin_notes = admin_notes

            db.session.add(ActivityLog(
                action='Variance Declared: Warehouse Miscount/Charge',
                details=f"Admin {current_user.full_name} declared variance on {req_ref} as Warehouse Miscount/Charge (Accountable: Warehouse). Notes: {admin_notes}",
                timestamp=now,
                company_id=req.company_id
            ))

        elif resolution_type == 'warehouse_over_dispatch':
            # Warehouse Accountable: Warehouse over-dispatched / packed more goods than requisitioned
            for rec in records:
                item = rec.requisition_item
                product = item.product if item else None
                if not product:
                    continue

                if rec.variance_qty and rec.variance_qty > 0:
                    overage = abs(rec.variance_qty)
                    # Deduct over-dispatched stock from warehouse to reconcile physical goods sent
                    product.warehouse_qty = max(0, (product.warehouse_qty or 0) - overage)
                    product.quantity = (product.warehouse_qty or 0) + (product.store_qty or 0)

                    wb = WarehouseProductBatch.query.filter_by(product_id=product.id).filter(WarehouseProductBatch.quantity > 0).order_by(WarehouseProductBatch.exp_date.asc()).first()
                    if wb:
                        wb.quantity = max(0, wb.quantity - overage)

                    over_hist = ProductHistory(
                        product_id=product.id,
                        trxn_date=now,
                        trxn_code='WH OVERAGE',
                        payee=f"WAREHOUSE OVER-DISPATCH ({req.branch or req.requested_by})",
                        quantity_in=0.0,
                        quantity_out=overage,
                        net_change=-overage,
                        reference_id=req.id,
                        reference_type='warehouse_over_dispatch',
                        notes=f"Warehouse over-dispatch approved by {current_user.full_name}. Accountable: Warehouse. Deducted {overage} {item.uom or ''} from warehouse inventory. Notes: {admin_notes}",
                        company_id=req.company_id,
                    )
                    db.session.add(over_hist)

                rec.status = 'resolved'
                rec.resolution_type = 'warehouse_over_dispatch'
                rec.admin_notes = admin_notes
                rec.resolved_by = current_user.id
                rec.resolved_at = now

            req.status = 'Delivered'
            req.variance_resolution = 'warehouse_over_dispatch'
            req.variance_resolved_by = current_user.id
            req.variance_resolved_at = now
            req.variance_admin_notes = admin_notes

            db.session.add(ActivityLog(
                action='Variance Declared: Warehouse Over-Dispatch',
                details=f"Admin {current_user.full_name} declared variance on {req_ref} as Warehouse Over-Dispatch (Accountable: Warehouse). Notes: {admin_notes}",
                timestamp=now,
                company_id=req.company_id
            ))

        elif resolution_type == 'warehouse_damaged_prep':
            # Warehouse Accountable: Damaged in warehouse during picking/staging prior to transport
            for rec in records:
                item = rec.requisition_item
                product = item.product if item else None
                if not product:
                    continue

                if rec.variance_qty and rec.variance_qty < 0:
                    shortage = abs(rec.variance_qty)
                    wh_dmg_hist = ProductHistory(
                        product_id=product.id,
                        trxn_date=now,
                        trxn_code='WH DAMAGE',
                        payee=f"WH PRE-DISPATCH DAMAGE ({req.branch or req.requested_by})",
                        quantity_in=0.0,
                        quantity_out=shortage,
                        net_change=-shortage,
                        reference_id=req.id,
                        reference_type='warehouse_damaged_prep',
                        notes=f"Warehouse pre-dispatch damage logged by {current_user.full_name}. Accountable: Warehouse. Written off {shortage} {item.uom or ''}. Notes: {admin_notes}",
                        company_id=req.company_id,
                    )
                    db.session.add(wh_dmg_hist)

                rec.status = 'resolved'
                rec.resolution_type = 'warehouse_damaged_prep'
                rec.admin_notes = admin_notes
                rec.resolved_by = current_user.id
                rec.resolved_at = now

            req.status = 'Delivered'
            req.variance_resolution = 'warehouse_damaged_prep'
            req.variance_resolved_by = current_user.id
            req.variance_resolved_at = now
            req.variance_admin_notes = admin_notes

            db.session.add(ActivityLog(
                action='Variance Declared: Warehouse Pre-Dispatch Damage',
                details=f"Admin {current_user.full_name} declared variance on {req_ref} as Warehouse Pre-Dispatch Damage (Accountable: Warehouse). Notes: {admin_notes}",
                timestamp=now,
                company_id=req.company_id
            ))

        elif resolution_type == 'store_wrong_count':
            # Store Accountable: Store staff miscounted upon arrival; correct store inventory to actual received
            for rec in records:
                item = rec.requisition_item
                product = item.product if item else None
                if not product:
                    continue

                if rec.variance_qty and rec.variance_qty < 0:
                    shortage = abs(rec.variance_qty)
                    # Correct store inventory up to match actual physical goods
                    product.store_qty = (product.store_qty or 0) + shortage
                    product.quantity = (product.warehouse_qty or 0) + (product.store_qty or 0)
                    rec.received_qty = rec.released_qty

                    corr_hist = ProductHistory(
                        product_id=product.id,
                        trxn_date=now,
                        trxn_code='COUNT CORRECTION',
                        payee=f"STORE MISCOUNT CORRECTION ({req.branch or req.requested_by})",
                        quantity_in=shortage,
                        quantity_out=0.0,
                        net_change=shortage,
                        reference_id=req.id,
                        reference_type='store_wrong_count',
                        notes=f"Store miscount corrected by {current_user.full_name}. Accountable: Store Staff. Added {shortage} {item.uom or ''} to store inventory. Notes: {admin_notes}",
                        company_id=req.company_id,
                    )
                    db.session.add(corr_hist)
                elif rec.variance_qty and rec.variance_qty > 0:
                    overage = abs(rec.variance_qty)
                    product.store_qty = max(0, (product.store_qty or 0) - overage)
                    product.quantity = (product.warehouse_qty or 0) + (product.store_qty or 0)
                    rec.received_qty = rec.released_qty

                    corr_hist = ProductHistory(
                        product_id=product.id,
                        trxn_date=now,
                        trxn_code='COUNT CORRECTION',
                        payee=f"STORE MISCOUNT CORRECTION ({req.branch or req.requested_by})",
                        quantity_in=0.0,
                        quantity_out=overage,
                        net_change=-overage,
                        reference_id=req.id,
                        reference_type='store_wrong_count',
                        notes=f"Store miscount corrected by {current_user.full_name}. Accountable: Store Staff. Deducted {overage} {item.uom or ''} from store inventory. Notes: {admin_notes}",
                        company_id=req.company_id,
                    )
                    db.session.add(corr_hist)

                rec.status = 'resolved'
                rec.resolution_type = 'store_wrong_count'
                rec.admin_notes = admin_notes
                rec.resolved_by = current_user.id
                rec.resolved_at = now

            req.status = 'Delivered'
            req.variance_resolution = 'store_wrong_count'
            req.variance_resolved_by = current_user.id
            req.variance_resolved_at = now
            req.variance_admin_notes = admin_notes

            db.session.add(ActivityLog(
                action='Variance Declared: Store Wrong Count',
                details=f"Admin {current_user.full_name} declared variance on {req_ref} as Store Counting Error (Accountable: Store Staff). Notes: {admin_notes}",
                timestamp=now,
                company_id=req.company_id
            ))

        elif resolution_type == 'store_damage_unloading':
            # Store Accountable: Dropped or damaged by store staff during unloading/shelving
            for rec in records:
                item = rec.requisition_item
                product = item.product if item else None
                if not product:
                    continue

                if rec.variance_qty and rec.variance_qty < 0:
                    shortage = abs(rec.variance_qty)
                    store_dmg_hist = ProductHistory(
                        product_id=product.id,
                        trxn_date=now,
                        trxn_code='STORE LOSS',
                        payee=f"STORE UNLOADING DAMAGE ({req.branch or req.requested_by})",
                        quantity_in=0.0,
                        quantity_out=shortage,
                        net_change=-shortage,
                        reference_id=req.id,
                        reference_type='store_damage_unloading',
                        notes=f"Store unloading damage logged by {current_user.full_name}. Accountable: Store Staff. Loss {shortage} {item.uom or ''}. Notes: {admin_notes}",
                        company_id=req.company_id,
                    )
                    db.session.add(store_dmg_hist)

                rec.status = 'resolved'
                rec.resolution_type = 'store_damage_unloading'
                rec.admin_notes = admin_notes
                rec.resolved_by = current_user.id
                rec.resolved_at = now

            req.status = 'Delivered'
            req.variance_resolution = 'store_damage_unloading'
            req.variance_resolved_by = current_user.id
            req.variance_resolved_at = now
            req.variance_admin_notes = admin_notes

            db.session.add(ActivityLog(
                action='Variance Declared: Store Unloading Damage',
                details=f"Admin {current_user.full_name} declared variance on {req_ref} as Store Unloading Damage (Accountable: Store Staff). Notes: {admin_notes}",
                timestamp=now,
                company_id=req.company_id
            ))

        elif resolution_type == 'store_missing_post_delivery':
            # Store Accountable: Received into store premises, but misplaced or lost after driver departure
            for rec in records:
                item = rec.requisition_item
                product = item.product if item else None
                if not product:
                    continue

                if rec.variance_qty and rec.variance_qty < 0:
                    shortage = abs(rec.variance_qty)
                    store_loss_hist = ProductHistory(
                        product_id=product.id,
                        trxn_date=now,
                        trxn_code='STORE LOSS',
                        payee=f"STORE MISPLACEMENT ({req.branch or req.requested_by})",
                        quantity_in=0.0,
                        quantity_out=shortage,
                        net_change=-shortage,
                        reference_id=req.id,
                        reference_type='store_missing_post_delivery',
                        notes=f"Store post-delivery misplacement logged by {current_user.full_name}. Accountable: Store Staff. Missing {shortage} {item.uom or ''}. Notes: {admin_notes}",
                        company_id=req.company_id,
                    )
                    db.session.add(store_loss_hist)

                rec.status = 'resolved'
                rec.resolution_type = 'store_missing_post_delivery'
                rec.admin_notes = admin_notes
                rec.resolved_by = current_user.id
                rec.resolved_at = now

            req.status = 'Delivered'
            req.variance_resolution = 'store_missing_post_delivery'
            req.variance_resolved_by = current_user.id
            req.variance_resolved_at = now
            req.variance_admin_notes = admin_notes

            db.session.add(ActivityLog(
                action='Variance Declared: Store Misplacement',
                details=f"Admin {current_user.full_name} declared variance on {req_ref} as Store Misplacement Post-Delivery (Accountable: Store Staff). Notes: {admin_notes}",
                timestamp=now,
                company_id=req.company_id
            ))

        elif resolution_type == 'restore_warehouse':
            # Recovery Action: Stock retained at or returned to warehouse
            for rec in records:
                item = rec.requisition_item
                product = item.product if item else None
                if not product:
                    continue

                if rec.variance_qty and rec.variance_qty < 0:
                    shortage = abs(rec.variance_qty)
                    product.warehouse_qty = (product.warehouse_qty or 0) + shortage
                    product.quantity = (product.warehouse_qty or 0) + (product.store_qty or 0)

                    wb = WarehouseProductBatch.query.filter_by(
                        product_id=product.id,
                    ).filter(WarehouseProductBatch.quantity > 0).order_by(WarehouseProductBatch.exp_date.asc()).first()
                    if wb:
                        wb.quantity += shortage
                    else:
                        any_wb = WarehouseProductBatch.query.filter_by(product_id=product.id).order_by(WarehouseProductBatch.added_on.desc()).first()
                        if any_wb:
                            any_wb.quantity += shortage

                    ret_hist = ProductHistory(
                        product_id=product.id,
                        trxn_date=now,
                        trxn_code='TRANS IN',
                        payee=f"RETURN-TO-WAREHOUSE ({req.branch or req.requested_by})",
                        quantity_in=shortage,
                        quantity_out=0.0,
                        net_change=shortage,
                        reference_id=req.id,
                        reference_type='restore_warehouse',
                        notes=f"Restored to warehouse by {current_user.full_name}. Restored {shortage} {item.uom or ''}. Notes: {admin_notes}",
                        company_id=req.company_id,
                    )
                    db.session.add(ret_hist)

                rec.status = 'resolved'
                rec.resolution_type = 'restore_warehouse'
                rec.admin_notes = admin_notes
                rec.resolved_by = current_user.id
                rec.resolved_at = now

            req.status = 'Delivered'
            req.variance_resolution = 'restore_warehouse'
            req.variance_resolved_by = current_user.id
            req.variance_resolved_at = now
            req.variance_admin_notes = admin_notes

            db.session.add(ActivityLog(
                action='Variance Declared: Restored in Warehouse',
                details=f"Admin {current_user.full_name} declared variance on {req_ref} as Restored in Warehouse. Warehouse stock restored. Notes: {admin_notes}",
                timestamp=now,
                company_id=req.company_id
            ))

        elif resolution_type == 'restore_store':
            # Recovery Action: Stock recovered / found in store or delivered later to the store
            for rec in records:
                item = rec.requisition_item
                product = item.product if item else None
                if not product:
                    continue

                if rec.variance_qty and rec.variance_qty < 0:
                    shortage = abs(rec.variance_qty)
                    product.store_qty = (product.store_qty or 0) + shortage
                    product.quantity = (product.warehouse_qty or 0) + (product.store_qty or 0)
                    rec.received_qty = rec.released_qty

                    recov_hist = ProductHistory(
                        product_id=product.id,
                        trxn_date=now,
                        trxn_code='STORE RECOVERY',
                        payee=f"RESTORED IN STORE ({req.branch or req.requested_by})",
                        quantity_in=shortage,
                        quantity_out=0.0,
                        net_change=shortage,
                        reference_id=req.id,
                        reference_type='restore_store',
                        notes=f"Restored in store inventory by {current_user.full_name}: {shortage} {item.uom or ''}. Notes: {admin_notes}",
                        company_id=req.company_id,
                    )
                    db.session.add(recov_hist)

                rec.status = 'resolved'
                rec.resolution_type = 'restore_store'
                rec.admin_notes = admin_notes
                rec.resolved_by = current_user.id
                rec.resolved_at = now

            req.status = 'Delivered'
            req.variance_resolution = 'restore_store'
            req.variance_resolved_by = current_user.id
            req.variance_resolved_at = now
            req.variance_admin_notes = admin_notes

            db.session.add(ActivityLog(
                action='Variance Declared: Restored in Store',
                details=f"Admin {current_user.full_name} declared variance on {req_ref} as Restored in Store. Store stock updated. Notes: {admin_notes}",
                timestamp=now,
                company_id=req.company_id
            ))

        elif resolution_type == 'supplier_defect':
            # Supplier Accountable: Manufacturer defect, broken factory seal, or underweight unit
            for rec in records:
                item = rec.requisition_item
                product = item.product if item else None
                if not product:
                    continue

                if rec.variance_qty and rec.variance_qty < 0:
                    shortage = abs(rec.variance_qty)
                    supp_hist = ProductHistory(
                        product_id=product.id,
                        trxn_date=now,
                        trxn_code='SUPPLIER DEFECT',
                        payee=f"SUPPLIER DEFECT ({req.branch or req.requested_by})",
                        quantity_in=0.0,
                        quantity_out=shortage,
                        net_change=-shortage,
                        reference_id=req.id,
                        reference_type='supplier_defect',
                        notes=f"Supplier defect logged by {current_user.full_name}. Claimable against vendor. Defective {shortage} {item.uom or ''}. Notes: {admin_notes}",
                        company_id=req.company_id,
                    )
                    db.session.add(supp_hist)

                rec.status = 'resolved'
                rec.resolution_type = 'supplier_defect'
                rec.admin_notes = admin_notes
                rec.resolved_by = current_user.id
                rec.resolved_at = now

            req.status = 'Delivered'
            req.variance_resolution = 'supplier_defect'
            req.variance_resolved_by = current_user.id
            req.variance_resolved_at = now
            req.variance_admin_notes = admin_notes

            db.session.add(ActivityLog(
                action='Variance Declared: Supplier Defect',
                details=f"Admin {current_user.full_name} declared variance on {req_ref} as Manufacturer / Supplier Defect (Accountable: Supplier). Notes: {admin_notes}",
                timestamp=now,
                company_id=req.company_id
            ))

        elif resolution_type == 'recount':
            # Investigation Action: Reject store declaration and request a recount
            for rec in records:
                item = rec.requisition_item
                product = item.product if item else None
                if not product:
                    continue

                if rec.variance_type == 'short':
                    shortage = abs(rec.variance_qty or 0)
                    product.store_qty = (product.store_qty or 0) + shortage
                elif rec.variance_type == 'over':
                    overage = abs(rec.variance_qty or 0)
                    product.store_qty = max(0, (product.store_qty or 0) - overage)
                product.quantity = (product.warehouse_qty or 0) + (product.store_qty or 0)

                rec.status = 'recount_requested'
                rec.resolution_type = 'recount'
                rec.admin_notes = admin_notes
                rec.resolved_by = current_user.id
                rec.resolved_at = now

            req.status = 'approved'
            req.date_of_delivery = None
            req.variance_resolution = 'recount'
            req.variance_resolved_by = current_user.id
            req.variance_resolved_at = now
            req.variance_admin_notes = admin_notes

            db.session.add(ActivityLog(
                action='Delivery Recount Requested',
                details=f"Admin {current_user.full_name} rejected declaration on {req_ref} and requested a store recount. Notes: {admin_notes}",
                timestamp=now,
                company_id=req.company_id
            ))

        # Notify store user and stakeholders
        try:
            from helpers import create_notification
            title_map = {
                'damaged_loss': 'In-Transit Loss / Damaged (Accountable: Delivery / Driver)',
                'delivery_transit_loss': 'In-Transit Loss / Damaged (Accountable: Delivery / Driver)',
                'delivery_spoilage_delay': 'In-Transit Spoilage / Delay (Accountable: Delivery / Driver)',
                'warehouse_miscount_charge': 'Warehouse Release Miscount / Charge (Accountable: Warehouse)',
                'warehouse_over_dispatch': 'Warehouse Over-Dispatch / Excess (Accountable: Warehouse)',
                'warehouse_damaged_prep': 'Warehouse Pre-Dispatch Damage (Accountable: Warehouse)',
                'store_wrong_count': 'Store Counting Error Corrected (Accountable: Store Staff)',
                'store_damage_unloading': 'Store Unloading Damage (Accountable: Store Staff)',
                'store_missing_post_delivery': 'Store Misplacement Post-Delivery (Accountable: Store Staff)',
                'restore_warehouse': 'Restored in Warehouse (Returned / Retained)',
                'restore_store': 'Restored in Store (Recovered / Follow-up Delivered)',
                'supplier_defect': 'Manufacturer / Supplier Defect (Accountable: Supplier)',
                'recount': 'Store Recount Requested',
            }
            display_title = title_map.get(resolution_type, resolution_type.replace('_', ' ').title())

            # Notify requester if user_id exists
            if hasattr(req, 'user_id') and req.user_id:
                create_notification(
                    user_id=req.user_id,
                    title=f"Delivery Variance Resolved: {display_title} ({req_ref})",
                    message=f"Variance on {req_ref} was declared as '{display_title}' by {current_user.full_name}. Notes: {admin_notes or 'None'}",
                    type="info" if resolution_type != 'recount' else "warning",
                    reference_type="delivery_variance",
                    reference_id=req.id
                )
        except Exception as notif_err:
            print(f"Error creating notification: {notif_err}")

        db.session.commit()
        return jsonify({
            'success': True,
            'message': f'Variance successfully resolved as {resolution_type.replace("_", " ").title()}.',
            'status': req.status
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Failed to resolve variance: {str(e)}'}), 500


# ─────────────────────────────────────────────────
#  DELIVERY VARIANCES PAGE & API — Admin Dedicated Hub
# ─────────────────────────────────────────────────
@receiving_bp.route('/variances')
@login_required
def variance_page():
    return render_template('receiving/variances.html')


@receiving_bp.route('/api/variances')
@login_required
def api_variances():
    from sqlalchemy import or_

    status_filter = request.args.get('status', 'all')
    search = request.args.get('q', '').strip()
    date_from = request.args.get('from', '')
    date_to = request.args.get('to', '')

    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        base = Requisition.query
    else:
        base = Requisition.query.filter_by(company_id=current_user.company_id)

    # Filter to requisitions with variances or discrepancy status
    base = base.filter(
        or_(
            Requisition.has_variance == True,
            Requisition.status.in_(['Discrepancy - Pending Approval', 'Variance - Pending Approval'])
        )
    )

    if status_filter == 'pending':
        base = base.filter(Requisition.status.in_(['Discrepancy - Pending Approval', 'Variance - Pending Approval']))
    elif status_filter == 'resolved':
        base = base.filter(Requisition.status.notin_(['Discrepancy - Pending Approval', 'Variance - Pending Approval']))

    if search:
        base = base.filter(
            or_(
                Requisition.branch.ilike(f'%{search}%'),
                Requisition.requested_by.ilike(f'%{search}%')
            )
        )

    if date_from:
        base = base.filter(Requisition.date_of_delivery >= datetime.fromisoformat(date_from))
    if date_to:
        base = base.filter(Requisition.date_of_delivery <= datetime.fromisoformat(date_to) + timedelta(days=1))

    requisitions = base.order_by(Requisition.id.desc()).all()

    rows = []
    for req in requisitions:
        items = []
        total_requested = 0
        total_released = 0
        total_received = 0
        total_variance = 0
        total_short = 0
        total_over = 0
        res_info = None

        for item in req.items:
            rec = ReceivingRecord.query.filter_by(
                requisition_item_id=item.id,
                requisition_id=req.id
            ).first()
            released = rec.released_qty if (rec and rec.released_qty is not None) else (item.released_quantity if item.released_quantity is not None else item.quantity)
            received = rec.received_qty if rec else 0
            variance = rec.variance_qty if rec else 0
            vtype = rec.variance_type if rec else 'exact'

            total_requested += (item.quantity or 0)
            total_released += released
            total_received += received
            total_variance += variance
            if variance < 0:
                total_short += abs(variance)
            elif variance > 0:
                total_over += variance

            if rec and (rec.resolution_type or rec.admin_notes) and not res_info:
                res_info = {
                    'resolution_type': rec.resolution_type,
                    'admin_notes': rec.admin_notes,
                    'resolved_at': rec.resolved_at.strftime('%Y-%m-%d %I:%M %p') if rec.resolved_at else '',
                    'resolved_by_name': rec.resolved_by_user.full_name if rec.resolved_by_user else 'Admin'
                }

            items.append({
                'id': item.id,
                'product_name': item.product.name if item.product else 'Unknown',
                'uom': item.uom,
                'requested': item.quantity,
                'released': released,
                'received': received,
                'variance': variance,
                'variance_type': vtype,
                'status': rec.status if rec else 'pending',
                'resolution_type': rec.resolution_type if rec else None,
                'admin_notes': rec.admin_notes if rec else None,
            })

        ref = f"REQ-{req.date_created.year}-{req.id:04d}" if req.date_created else f"REQ-{req.id}"
        has_pending = (req.status in ('Discrepancy - Pending Approval', 'Variance - Pending Approval'))

        rows.append({
            'id': req.id,
            'ref': ref,
            'branch': req.branch,
            'requested_by': req.requested_by,
            'status': req.status,
            'has_pending': has_pending,
            'can_resolve': (current_user.role in ['Company-Admin', 'SYS-Admin']) and has_pending,
            'is_company_admin': current_user.role in ['Company-Admin', 'SYS-Admin'],
            'date_created': req.date_created.strftime('%Y-%m-%d %I:%M %p') if req.date_created else '',
            'date_of_delivery': req.date_of_delivery.strftime('%Y-%m-%d %I:%M %p') if req.date_of_delivery else '',
            'items': items,
            'total_requested': total_requested,
            'total_released': total_released,
            'total_received': total_received,
            'total_variance': total_variance,
            'total_short': total_short,
            'total_over': total_over,
            'variance_summary': req.variance_summary,
            'variance_resolution': req.variance_resolution,
            'variance_admin_notes': req.variance_admin_notes,
            'variance_resolved_at': req.variance_resolved_at.strftime('%Y-%m-%d %I:%M %p') if req.variance_resolved_at else '',
            'variance_resolved_by': req.variance_resolver.full_name if req.variance_resolver else None,
            'resolution_info': res_info,
            'item_count': len(items),
        })

    return jsonify({'success': True, 'rows': rows})

