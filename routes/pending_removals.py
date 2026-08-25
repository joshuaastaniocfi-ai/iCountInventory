from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import desc

from extensions import db
from models import PendingRemoval, Product, WarehouseProductBatch, StoreProductBatch, ProductHistory, User
from helpers import user_redirect_to_requisition, admin_required, sys_admin_required, edit_delete_required, log_activity, assign_company, create_notification

# Create blueprint with URL prefix as required by project specifications
pending_removals = Blueprint('pending_removals', __name__, url_prefix='/pending-removals')


@pending_removals.route('/')
@login_required
@admin_required
def pending_removals_list():
    """Display list of pending removals"""
    if current_user.role == 'SYS-Admin':
        # SYS-Admin can see all pending removals
        pending_list = (PendingRemoval.query
                       .filter_by(status='Pending')
                       .order_by(desc(PendingRemoval.created_at))
                       .all())
    elif current_user.role == 'Company-Admin':
        # Company-Admin can see pending removals from their company
        pending_list = (PendingRemoval.query
                       .filter_by(status='Pending', company_id=current_user.company_id)
                       .order_by(desc(PendingRemoval.created_at))
                       .all())
    else:
        # WH-Admin can only see their own pending removals
        pending_list = (PendingRemoval.query
                       .filter_by(status='Pending', requested_by=current_user.id)
                       .order_by(desc(PendingRemoval.created_at))
                       .all())
    
    return render_template('warehouse/pending_removals.html', pending_removals=pending_list)


@pending_removals.route('/request-removal', methods=['POST'])
@login_required
@edit_delete_required
def request_removal():
    """Create a new pending removal request"""
    try:
        data = request.get_json()
        product_id = data.get('product_id')
        batch_id = data.get('batch_id')
        quantity = float(data.get('quantity'))
        reason = data.get('reason')
        remarks = data.get('remarks', '')

        # Validate required fields
        if not all([product_id, batch_id, quantity, reason]):
            return jsonify({'status': 'error', 'message': 'Missing required fields'}), 400

        # Check if batch exists and belongs to product
        batch = WarehouseProductBatch.query.get(batch_id)
        if not batch or batch.product_id != int(product_id):
            return jsonify({'status': 'error', 'message': 'Invalid batch selected'}), 400

        # Check if product exists
        product = Product.query.get(product_id)
        if not product:
            return jsonify({'status': 'error', 'message': 'Product not found'}), 404

        # Check if enough stock is available
        if batch.quantity < quantity:
            return jsonify({
                'status': 'error', 
                'message': f'Not enough stock in selected batch. Available: {batch.quantity}'
            }), 400

        # Create pending removal request
        pending_removal = PendingRemoval(
            product_id=product_id,
            batch_id=batch_id,
            requested_by=current_user.id,
            quantity=quantity,
            reason=reason,
            remarks=remarks,
            company_id=current_user.company_id  # Assign company_id from current user
        )

        db.session.add(pending_removal)
        db.session.commit()

        # Log activity
        log_activity(
            action="Request Stock Removal",
            details=(f"<strong>{quantity} {product.uom}</strong> removal requested for "
                    f"<strong>{product.name}</strong><br>"
                    f"Batch #{batch.id} (Exp: {batch.exp_date.strftime('%Y-%m-%d')})<br>"
                    f"Reason: {reason}<br>"
                    f"Remarks: {remarks}<br>"
                    f"Status: <span class='badge bg-warning'>Pending Approval</span>")
        )

        return jsonify({
            'status': 'success', 
            'message': 'Removal request submitted successfully. Waiting for SYS-Admin approval.'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@pending_removals.route('/approve-removal/<int:removal_id>', methods=['POST'])
@login_required
@edit_delete_required
def approve_removal(removal_id):
    """Approve a pending removal request"""
    try:
        data = request.get_json()
        review_remarks = data.get('review_remarks', '')

        pending_removal = PendingRemoval.query.get_or_404(removal_id)
        
        # Check if Company-Admin can only approve requests from their company
        if current_user.role == 'Company-Admin' and pending_removal.company_id != current_user.company_id:
            return jsonify({'status': 'error', 'message': 'Access denied. You can only approve requests from your company.'}), 403
        
        if pending_removal.status != 'Pending':
            return jsonify({'status': 'error', 'message': 'Removal request is not pending'}), 400

        # Get related objects
        batch = pending_removal.batch
        product = pending_removal.product
        requester = pending_removal.requester

        # Check if still enough stock is available
        if batch.quantity < pending_removal.quantity:
            return jsonify({
                'status': 'error', 
                'message': f'Not enough stock available. Current batch quantity: {batch.quantity}'
            }), 400

        # Update batch quantity
        batch.quantity -= pending_removal.quantity

        # Update product total quantity
        product.quantity -= pending_removal.quantity
        product.last_updated = datetime.now(ZoneInfo("Asia/Manila"))

        # Create ProductHistory record for TRANS OUT
        current_time = datetime.now(ZoneInfo("Asia/Manila"))
        history_record = ProductHistory(
            product_id=pending_removal.product_id,
            trxn_date=current_time,
            trxn_code='TRANS OUT',
            payee=f'Approved Removal - {pending_removal.reason}',
            quantity_in=0.0,
            quantity_out=pending_removal.quantity,
            net_change=-pending_removal.quantity,
            reference_id=batch.id,
            reference_type='batch'
        )
        # Assign company_id to the history record
        history_record = assign_company(history_record)
        db.session.add(history_record)

        # Update pending removal status
        pending_removal.status = 'Approved'
        pending_removal.reviewed_by = current_user.id
        pending_removal.reviewed_at = current_time
        pending_removal.review_remarks = review_remarks

        db.session.commit()

        # Log activity
        log_activity(
            action="Approve Stock Removal",
            details=(f"<strong>{pending_removal.quantity} {product.uom}</strong> removal approved for "
                    f"<strong>{product.name}</strong><br>"
                    f"Requested by: {requester.full_name}<br>"
                    f"Batch #{batch.id} (Exp: {batch.exp_date.strftime('%Y-%m-%d')})<br>"
                    f"Reason: {pending_removal.reason}<br>"
                    f"Review remarks: {review_remarks}<br>"
                    f"Remaining in batch: {batch.quantity} {product.uom}<br>"
                    f"Total remaining: <span class='badge bg-warning'>{product.quantity} {product.uom}</span>")
        )

        # Notify requester
        try:
            create_notification(
                user_id=requester.id,
                title=f'Removal Request #{pending_removal.id} Approved',
                message=f'{pending_removal.quantity} {product.uom} of {product.name} removal has been approved.',
                type='success',
                reference_type='removal',
                reference_id=pending_removal.id
            )
        except Exception:
            pass

        return jsonify({'status': 'success', 'message': 'Removal request approved successfully'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@pending_removals.route('/reject-removal/<int:removal_id>', methods=['POST'])
@login_required
@edit_delete_required
def reject_removal(removal_id):
    """Reject a pending removal request"""
    try:
        data = request.get_json()
        review_remarks = data.get('review_remarks', '')

        pending_removal = PendingRemoval.query.get_or_404(removal_id)
        
        # Check if Company-Admin can only reject requests from their company
        if current_user.role == 'Company-Admin' and pending_removal.company_id != current_user.company_id:
            return jsonify({'status': 'error', 'message': 'Access denied. You can only reject requests from your company.'}), 403
        
        if pending_removal.status != 'Pending':
            return jsonify({'status': 'error', 'message': 'Removal request is not pending'}), 400

        # Update pending removal status
        pending_removal.status = 'Rejected'
        pending_removal.reviewed_by = current_user.id
        pending_removal.reviewed_at = datetime.now(ZoneInfo("Asia/Manila"))
        pending_removal.review_remarks = review_remarks

        db.session.commit()

        # Log activity
        log_activity(
            action="Reject Stock Removal",
            details=(f"Removal request rejected for <strong>{pending_removal.product.name}</strong><br>"
                    f"Requested by: {pending_removal.requester.full_name}<br>"
                    f"Quantity: {pending_removal.quantity} {pending_removal.product.uom}<br>"
                    f"Reason: {pending_removal.reason}<br>"
                    f"Rejection remarks: {review_remarks}")
        )

        # Notify requester
        try:
            create_notification(
                user_id=pending_removal.requester.id,
                title=f'Removal Request #{pending_removal.id} Rejected',
                message=f'{pending_removal.quantity} {pending_removal.product.uom} of {pending_removal.product.name} removal was rejected.',
                type='danger',
                reference_type='removal',
                reference_id=pending_removal.id
            )
        except Exception:
            pass

        return jsonify({'status': 'success', 'message': 'Removal request rejected successfully'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@pending_removals.route('/history')
@login_required
@admin_required
def removal_history():
    """Display removal request history"""
    if current_user.role == 'SYS-Admin':
        # SYS-Admin can see all removal history
        history_list = (PendingRemoval.query
                       .filter(PendingRemoval.status.in_(['Approved', 'Rejected']))
                       .order_by(desc(PendingRemoval.reviewed_at))
                       .all())
    elif current_user.role == 'Company-Admin':
        # Company-Admin can see removal history from their company
        history_list = (PendingRemoval.query
                       .filter_by(company_id=current_user.company_id)
                       .filter(PendingRemoval.status.in_(['Approved', 'Rejected']))
                       .order_by(desc(PendingRemoval.reviewed_at))
                       .all())
    else:
        # WH-Admin can only see their own removal history
        history_list = (PendingRemoval.query
                       .filter_by(requested_by=current_user.id)
                       .filter(PendingRemoval.status.in_(['Approved', 'Rejected']))
                       .order_by(desc(PendingRemoval.reviewed_at))
                       .all())
    
    return render_template('warehouse/removal_history.html', removal_history=history_list)
