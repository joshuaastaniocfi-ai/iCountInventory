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
    Product, WarehouseProductBatch, StoreProductBatch, ProductHistory, ReceivingRecord, ActivityLog
)

receiving_bp = Blueprint('receiving', __name__, url_prefix='/receiving')

PH_TZ = ZoneInfo("Asia/Manila")


def _company_guard(requisition):
    """Return True if current user may access this requisition."""
    return requisition.company_id == current_user.company_id


# ─────────────────────────────────────────────────
#  API LIST — JSON: requisitions ready for receiving
# ─────────────────────────────────────────────────
@receiving_bp.route('/api/list')
@login_required
def api_list_receiving():
    status_filter = request.args.get('status', 'all')
    search_q = request.args.get('q', '').strip().lower()

    # Show approved and dispatched requisitions (ready for delivery confirmation)
    query = Requisition.query.filter(
        Requisition.company_id == current_user.company_id,
        Requisition.status.in_(['approved', 'Dispatched', 'Delivered', 'Partial'])
    )

    if status_filter != 'all':
        if status_filter == 'pending':
            query = query.filter(Requisition.status.in_(['approved', 'Dispatched']))
        elif status_filter == 'delivered':
            query = query.filter(Requisition.status.in_(['Delivered']))
        elif status_filter == 'partial':
            query = query.filter(Requisition.status == 'Partial')

    requisitions = query.order_by(Requisition.date_created.desc()).all()

    if search_q:
        def matches(r):
            ref = f"REQ-{r.date_created.year}-{r.id:04d}".lower()
            if search_q in ref or search_q in str(r.id).lower():
                return True
            return any(search_q in item.product.name.lower() for item in r.items)
        requisitions = [r for r in requisitions if matches(r)]

    rows = []
    for r in requisitions:
        ref = f"REQ-{r.date_created.year}-{r.id:04d}"

        # Determine item statuses from receiving records
        all_delivered = True
        any_received = False
        for item in r.items:
            records = ReceivingRecord.query.filter_by(requisition_item_id=item.id).all()
            if records:
                any_received = True
                total_received = sum(rec.received_qty for rec in records)
                if total_received < item.quantity:
                    all_delivered = False
            else:
                all_delivered = False

        if all_delivered and r.items:
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

        # Check existing receiving record
        existing = ReceivingRecord.query.filter_by(
            requisition_item_id=item.id,
            requisition_id=req.id
        ).first()

        warehouse_released = existing.released_qty if existing else item.quantity

        items.append({
            'item_id': item.id,
            'product_id': product.id if product else None,
            'product_name': product.name if product else 'Unknown',
            'uom': item.uom,
            'warehouse_released': warehouse_released,
            'warehouse_stock': product.quantity if product else 0,
            'received_qty': existing.received_qty if existing else None,
            'variance_qty': existing.variance_qty if existing else None,
            'variance_type': existing.variance_type if existing else None,
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
            'is_optional': True,
        })

    return jsonify({
        'success': True,
        'requisition': {
            'id': req.id,
            'ref': ref,
            'status': req.status,
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

        # Read warehouse-released qty (editable by warehouse)
        raw_released = data.get(released_key, '').strip() if isinstance(data, dict) else request.form.get(released_key, '').strip()
        if raw_released:
            try:
                warehouse_released = float(raw_released)
            except ValueError:
                errors.append(f'Invalid released quantity for {item.product.name}')
                continue
        else:
            warehouse_released = item.quantity

        variance_qty = actual_qty - warehouse_released
        if variance_qty > 0:
            variance_type = 'over'
        elif variance_qty < 0:
            variance_type = 'short'
        else:
            variance_type = 'exact'

        existing_record = ReceivingRecord.query.filter_by(
            requisition_item_id=item.id,
            requisition_id=req.id
        ).first()

        if existing_record:
            existing_record.released_qty = warehouse_released
            existing_record.received_qty = actual_qty
            existing_record.variance_qty = variance_qty
            existing_record.variance_type = variance_type
            existing_record.confirmed_by = current_user.id
            existing_record.confirmed_at = now
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
                company_id=current_user.company_id,
            )
            db.session.add(record)

        # ProductHistory entry
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

        # Handle SHORT variance: restore undelivered qty back to warehouse
        if variance_type == 'short':
            shortage_qty = abs(variance_qty)
            product = item.product
            if product:
                product.quantity += shortage_qty

                deductions = RequisitionBatchDeduction.query.filter_by(
                    requisition_item_id=item.id
                ).all()

                for ded in deductions:
                    batches = WarehouseProductBatch.query.filter_by(
                        product_id=product.id
                    ).order_by(WarehouseProductBatch.exp_date).all()

                    remaining_restore = shortage_qty
                    for batch in batches:
                        if remaining_restore <= 0:
                            break
                        batch.quantity += remaining_restore
                        remaining_restore = 0

                return_history = ProductHistory(
                    product_id=item.product_id,
                    trxn_date=now,
                    trxn_code='TRANS IN',
                    payee=f"RETURN-{req.branch or req.requested_by}",
                    quantity_in=shortage_qty,
                    quantity_out=0.0,
                    net_change=shortage_qty,
                    reference_id=req.id,
                    reference_type='receiving_variance',
                    company_id=current_user.company_id,
                )
                db.session.add(return_history)

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

        # Deduct released qty from warehouse stock (only on first save)
        if not existing_opt_item:
            product.quantity -= released_qty
            if product.quantity < 0:
                product.quantity = 0

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

        if existing_opt_rec:
            existing_opt_rec.released_qty = released_qty
            existing_opt_rec.received_qty = received_qty
            existing_opt_rec.variance_qty = var_qty
            existing_opt_rec.variance_type = var_type
            existing_opt_rec.confirmed_by = current_user.id
            existing_opt_rec.confirmed_at = now
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

        # Handle short for optional items (restore to warehouse)
        if var_type == 'short':
            shortage = abs(var_qty)
            product.quantity += shortage
            return_h = ProductHistory(
                product_id=product_id,
                trxn_date=now,
                trxn_code='TRANS IN',
                payee=f"RETURN-OPT-{req.branch or req.requested_by}",
                quantity_in=shortage,
                quantity_out=0.0,
                net_change=shortage,
                reference_id=req.id,
                reference_type='receiving_variance_opt',
                company_id=current_user.company_id,
            )
            db.session.add(return_h)

        if received_qty < released_qty:
            all_delivered = False

        opt_idx += 1

    if errors:
        return jsonify({'success': False, 'message': '; '.join(errors)}), 400

    # Also consider optional items ready for delivery status
    if not any_received:
        req.status = 'approved'

    # ── Status determination ──
    # Check all items (including optional) for delivery completeness
    total_items = sum(1 for it in req.items if not getattr(it, 'is_optional', False))
    optional_items = [it for it in req.items if getattr(it, 'is_optional', False)]
    all_regular_delivered = True
    for it in req.items:
        if getattr(it, 'is_optional', False):
            continue
        rec = ReceivingRecord.query.filter_by(requisition_item_id=it.id, requisition_id=req.id).first()
        if not rec or rec.received_qty < rec.released_qty:
            all_regular_delivered = False
            break

    if all_regular_delivered and all_delivered:
        req.status = 'Delivered'
    elif any_received:
        req.status = 'Partial'

    req.date_of_delivery = now

    # Activity log
    log = ActivityLog(
        action='Receiving confirmed',
        details=f'Requisition {req_id} receiving confirmed by {current_user.full_name}',
        timestamp=now,
        company_id=current_user.company_id,
    )
    db.session.add(log)

    try:
        db.session.commit()
        return jsonify({
            'success': True,
            'message': 'Receiving confirmed successfully.',
            'status': req.status
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'}), 500


# ─────────────────────────────────────────────────
#  HTML PAGES (keep existing for reference / future use)
# ─────────────────────────────────────────────────
@receiving_bp.route('/')
@login_required
def list_receiving():
    return render_template('receiving/list.html')


@receiving_bp.route('/<int:req_id>')
@login_required
def receiving_detail(req_id):
    req = Requisition.query.get_or_404(req_id)
    if not _company_guard(req):
        flash('Access denied.', 'danger')
        return redirect(url_for('receiving.list_receiving'))

    ref = f"REQ-{req.date_created.year}-{req.id:04d}"

    items = []
    for item in req.items:
        if getattr(item, 'is_optional', False):
            continue
        product = item.product
        existing = ReceivingRecord.query.filter_by(
            requisition_item_id=item.id,
            requisition_id=req.id
        ).first()
        warehouse_released = existing.released_qty if existing else item.quantity

        items.append({
            'item_id': item.id,
            'product_id': product.id if product else None,
            'product_name': product.name if product else 'Unknown',
            'uom': item.uom,
            'warehouse_released': warehouse_released,
            'warehouse_stock': product.quantity if product else 0,
            'received_qty': existing.received_qty if existing else None,
            'variance_qty': existing.variance_qty if existing else None,
            'variance_type': existing.variance_type if existing else None,
        })

    return render_template(
        'receiving/detail.html',
        req=req,
        ref=ref,
        items=items,
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
    else:
        base = Requisition.query.filter_by(company_id=current_user.company_id)

    base = base.filter(Requisition.status.in_(['Delivered', 'Partial']))

    if status_filter != 'all':
        base = base.filter(Requisition.status == status_filter)

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

    requisitions = base.order_by(Requisition.date_of_delivery.desc()).all()

    rows = []
    for req in requisitions:
        items = []
        total_released = 0
        total_received = 0
        total_variance = 0
        has_variance = False
        for item in req.items:
            rec = ReceivingRecord.query.filter_by(
                requisition_item_id=item.id,
                requisition_id=req.id
            ).first()
            released = rec.released_qty if rec else item.quantity
            received = rec.received_qty if rec else 0
            variance = rec.variance_qty if rec else 0
            vtype = rec.variance_type if rec else 'exact'
            if vtype != 'exact':
                has_variance = True
            total_released += released
            total_received += received
            total_variance += variance
            items.append({
                'id': item.id,
                'product_name': item.product.name if item.product else 'Unknown',
                'uom': item.uom,
                'released': released,
                'received': received,
                'variance': variance,
                'variance_type': vtype
            })
        ref = f"REQ-{req.date_created.year}-{req.id:04d}" if req.date_created else f"REQ-{req.id}"
        rows.append({
            'id': req.id,
            'ref': ref,
            'branch': req.branch,
            'requested_by': req.requested_by,
            'status': req.status,
            'date_created': req.date_created.strftime('%Y-%m-%d %I:%M %p') if req.date_created else '',
            'date_of_delivery': req.date_of_delivery.strftime('%Y-%m-%d %I:%M %p') if req.date_of_delivery else '',
            'items': items,
            'total_released': total_released,
            'total_received': total_received,
            'total_variance': total_variance,
            'has_variance': has_variance,
            'item_count': len(items)
        })

    return jsonify({'success': True, 'rows': rows})
