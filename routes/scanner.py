# Standard library imports
from datetime import datetime
from zoneinfo import ZoneInfo
import os

# Third-party imports
from flask import Blueprint, render_template, request, redirect, url_for, flash, make_response, jsonify, current_app
from flask_login import login_required, current_user

# Local imports
from helpers import user_redirect_to_requisition, admin_required, sys_admin_required, edit_delete_required, is_mobile_device, log_activity, assign_company, create_notification
from extensions import db
from models import Product, WarehouseProductBatch, StoreProductBatch, StockAudit, PendingRemoval, Requisition, RequisitionBatchDeduction, ProductHistory, BatchAudit, ReceivingRecord

# Create blueprint with URL prefix as required by project specifications
scanner = Blueprint('scanner', __name__, url_prefix='/scanner')


@scanner.route('/scanner')
@login_required
@admin_required  # Only SYS-Admin and WH-Admin can access
def scanner_view():
    # Check if user is accessing from mobile device
    user_agent = request.headers.get('User-Agent', '')
    is_mobile = is_mobile_device(user_agent)
    
    if not is_mobile:
        flash('Scanner is only available on mobile devices.', 'warning')
        return redirect(url_for('main.dashboard'))
    
    return render_template('warehouse/scan_add_remove.html', current_user=current_user)


@scanner.route('/mobile-scanner')
@login_required
@admin_required  # Only SYS-Admin and WH-Admin can access
def mobile_scanner():
    """Mobile-optimized scanner route with enhanced mobile detection"""
    user_agent = request.headers.get('User-Agent', '')
    is_mobile = is_mobile_device(user_agent)
    
    if not is_mobile:
        # Return JSON response for API calls
        if request.headers.get('Accept') == 'application/json':
            return jsonify({
                'success': False,
                'message': 'Scanner is only available on mobile devices',
                'redirect': url_for('main.dashboard')
            }), 403
        
        # Redirect for browser requests
        flash('Scanner is only available on mobile devices.', 'warning')
        return redirect(url_for('main.dashboard'))
    
    # Set mobile-specific headers
    response = make_response(render_template('warehouse/scan_add_remove.html', current_user=current_user))
    response.headers['X-Mobile-Only'] = 'true'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    
    return response


@scanner.route('/mobile-audit')
@login_required
@admin_required  # Only SYS-Admin and WH-Admin can access
def mobile_audit():
    """Mobile-optimized stock audit route"""
    user_agent = request.headers.get('User-Agent', '')
    is_mobile = is_mobile_device(user_agent)
    
    if not is_mobile:
        # Return JSON response for API calls
        if request.headers.get('Accept') == 'application/json':
            return jsonify({
                'success': False,
                'message': 'Mobile audit is only available on mobile devices',
                'redirect': url_for('main.dashboard')
            }), 403
        
        # Redirect for browser requests
        flash('Mobile audit is only available on mobile devices.', 'warning')
        return redirect(url_for('main.dashboard'))
    
    # Set mobile-specific headers
    response = make_response(render_template('warehouse/mobile_audit.html', current_user=current_user))
    response.headers['X-Mobile-Only'] = 'true'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    
    return response


@scanner.route('/submit_mobile_audit', methods=['POST'])
@login_required
@edit_delete_required
def submit_mobile_audit():
    """Submit mobile audit data"""
    try:
        data = request.get_json()
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Invalid JSON: {str(e)}'}), 400
    
    if not data:
        return jsonify({'status': 'error', 'message': 'No data received'}), 400
    
    audits = data.get('audits', [])
    verified_by = data.get('verified_by', '')
    
    if not verified_by.strip():
        return jsonify({'status': 'error', 'message': 'Auditor name is required'}), 400
    
    if not audits:
        return jsonify({'status': 'error', 'message': 'No audit data provided'}), 400
    
    try:
        # Generate batch label
        batch_label = f"AUDIT_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Process each audit
        for audit_data in audits:
            product_id = audit_data.get('product_id')
            recorded_quantity = audit_data.get('recorded_quantity', 0)
            actual_quantity = audit_data.get('actual_quantity', 0)
            
            if not product_id:
                continue
            
            # Calculate discrepancy
            discrepancy = actual_quantity - recorded_quantity
            
            # Create audit record
            audit = StockAudit(
                product_id=product_id,
                recorded_quantity=recorded_quantity,
                actual_quantity=actual_quantity,
                discrepancy=discrepancy,
                verified_by=verified_by,
                batch_label=batch_label
            )
            
            # Assign company to the audit record
            # First try to get company_id from the product
            product = Product.query.get(product_id)
            if product and product.company_id:
                audit.company_id = product.company_id
            # If product doesn't have company_id, try to get it from current user
            elif hasattr(current_user, 'company_id') and current_user.company_id:
                audit.company_id = current_user.company_id
            else:
                # If neither product nor user has company_id, return an error
                return jsonify({'status': 'error', 'message': 'Unable to determine company for audit record.'}), 400
            
            db.session.add(audit)
        
        db.session.commit()
        
        # Log the audit activity
        log_activity(
            action="Mobile Stock Audit",
            details=f"Submitted audit batch <strong>{batch_label}</strong> with "
                    f"<span class='badge bg-info'>{len(audits)} items</span> "
                    f"verified by <strong>{verified_by}</strong>"
        )
        
        return jsonify({
            'status': 'success', 
            'message': f'Audit submitted successfully! {len(audits)} items audited.',
            'batch_label': batch_label
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@scanner.route('/delete_batch', methods=['POST'])
@login_required
@edit_delete_required
def delete_batch():
    """Delete a product batch from the scanner interface"""
    try:
        data = request.get_json()
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Invalid JSON: {str(e)}'}), 400
    
    if not data:
        return jsonify({'status': 'error', 'message': 'No data received'}), 400
    
    product_id = data.get('product_id')
    batch_id = data.get('batch_id')
    
    if not all([product_id, batch_id]):
        missing_fields = []
        if not product_id:
            missing_fields.append('product_id')
        if not batch_id:
            missing_fields.append('batch_id')
        error_msg = f'Missing required fields: {", ".join(missing_fields)}'
        return jsonify({'status': 'error', 'message': error_msg}), 400

    # Convert to integers to ensure proper type matching
    try:
        product_id = int(product_id)
        batch_id = int(batch_id)
    except (ValueError, TypeError) as e:
        error_msg = f'Invalid product_id or batch_id format: {str(e)}'
        return jsonify({'status': 'error', 'message': error_msg}), 400

    try:
        # Check if batch exists and belongs to the user's company
        # SYS-Admin with no company can delete batches from any company
        if current_user.role == 'SYS-Admin' and current_user.company_id is None:
            batch = WarehouseProductBatch.query.join(Product).filter(
                WarehouseProductBatch.id == batch_id,
                WarehouseProductBatch.product_id == product_id
            ).first()
        else:
            batch = WarehouseProductBatch.query.join(Product).filter(
                WarehouseProductBatch.id == batch_id,
                WarehouseProductBatch.product_id == product_id
            ).filter(
                Product.company_id == current_user.company_id
            ).first()

        if not batch:
            return jsonify({'status': 'error', 'message': 'Batch not found'}), 404

        # Check if product exists and belongs to the user's company
        if current_user.role == 'SYS-Admin' and current_user.company_id is None:
            # SYS-Admin can delete batches for any product
            product = Product.query.get(product_id)
        else:
            product = Product.query.filter_by(
                id=product_id,
                company_id=current_user.company_id
            ).first()

        if not product:
            return jsonify({'status': 'error', 'message': 'Product not found'}), 404

        # Check if batch is referenced in any pending removals (approved, rejected, or pending)
        pending_removals = PendingRemoval.query.filter_by(batch_id=batch_id).all()
        if pending_removals:
            # Remove the references to this batch in pending removals
            for removal in pending_removals:
                db.session.delete(removal)
            db.session.flush()  # Flush to remove the references

        # Update product quantities (batch belongs to warehouse)
        product.warehouse_qty -= batch.quantity
        if product.warehouse_qty < 0:
            product.warehouse_qty = 0
        product.quantity = product.warehouse_qty + product.store_qty

        # Delete the batch barcode image file before deleting the batch
        if batch.sub_barcode:
            try:
                # Determine the barcode image path
                if product.company_id:
                    barcode_image_path = os.path.join(current_app.root_path, 'static', 'batch_barcodes', f'company_{product.company_id}', f'{batch.sub_barcode}.png')
                else:
                    barcode_image_path = os.path.join(current_app.root_path, 'static', 'batch_barcodes', f'{batch.sub_barcode}.png')
                
                # Delete the barcode image file if it exists
                if os.path.exists(barcode_image_path):
                    os.remove(barcode_image_path)
            except Exception as e:
                # Log the error but don't stop the deletion process
                print(f"Warning: Could not delete barcode image for batch {batch.id}: {e}")

        # Log before deleting
        log_activity(
            action="Delete Batch",
            details=f"Deleted batch from <strong>{product.name}</strong> with "
                    f"quantity <span class='badge bg-info'>{batch.quantity} {product.uom}</span>, "
                    f"expiry: <strong>{batch.exp_date}</strong>"
        )

        db.session.delete(batch)
        db.session.commit()

        return jsonify({'status': 'success', 'message': 'Batch deleted successfully'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@scanner.route('/search_product_by_barcode')
@login_required
@admin_required
def search_product_by_barcode():
    """Search for a product by barcode"""
    barcode = request.args.get('barcode', '').strip()
    
    if not barcode:
        return jsonify({'success': False, 'message': 'Barcode is required'})
    
    # For SYS-Admin users, allow access to all products regardless of company
    if current_user.role == 'SYS-Admin':
        product = Product.query.filter_by(barcode=barcode).first()
    else:
        # For other users, check only in their company
        product = Product.query.filter_by(barcode=barcode, company_id=current_user.company_id).first()
    
    if not product:
        return jsonify({'success': False, 'message': 'Product not found'})
    
    # Get batches for this product
    batches = WarehouseProductBatch.query.filter_by(product_id=product.id).all()
    
    # Format batch data
    batch_data = []
    for batch in batches:
        batch_data.append({
            'id': batch.id,
            'exp_date': batch.exp_date.strftime('%Y-%m-%d') if batch.exp_date else None,
            'quantity': batch.quantity,
            'supplier_name': batch.supplier_name
        })
    
    return jsonify({
        'success': True,
        'product': {
            'id': product.id,
            'name': product.name,
            'barcode': product.barcode,
            'uom': product.uom,
            'current_quantity': product.quantity
        },
        'batches': batch_data
    })


@scanner.route('/lookup_batch_by_sub_barcode')
@login_required
@admin_required
def lookup_batch_by_sub_barcode():
    """Look up a batch by its sub-barcode and return the product_id"""
    sub_barcode = request.args.get('sub_barcode', '').strip()
    
    if not sub_barcode:
        return jsonify({'success': False, 'message': 'Sub-barcode is required'})
    
    # Search for batch by sub-barcode (exact match first)
    batch = WarehouseProductBatch.query.filter_by(sub_barcode=sub_barcode).first()
    
    # If not found, try with leading zeros stripped (backward compatibility)
    if not batch and sub_barcode.startswith('0'):
        stripped_barcode = sub_barcode.lstrip('0')
        batch = WarehouseProductBatch.query.filter_by(sub_barcode=stripped_barcode).first()
    
    # If still not found, try padding with zeros (for cases where database has leading zeros)
    if not batch:
        # Try with leading zeros (up to 13 digits)
        padded_barcode = sub_barcode.zfill(13)
        if padded_barcode != sub_barcode:
            batch = WarehouseProductBatch.query.filter_by(sub_barcode=padded_barcode).first()
    
    if not batch:
        return jsonify({'success': False, 'message': f'Batch not found for barcode: {sub_barcode}'})
    
    # Check if user has access to this batch (based on company)
    # Allow SYS-Admin to access all batches
    if current_user.role != 'SYS-Admin' and current_user.company_id and batch.product.company_id != current_user.company_id:
        return jsonify({'success': False, 'message': 'Access denied. Batch not found in your company'})
    
    return jsonify({
        'success': True,
        'batch': {
            'id': batch.id,
            'sub_barcode': batch.sub_barcode,  # Return the actual barcode as stored in DB
            'product_id': batch.product_id,
            'product_name': batch.product.name,
            'quantity': batch.quantity,
            'uom': batch.product.uom,
            'exp_date': batch.exp_date.strftime('%Y-%m-%d') if batch.exp_date else None
        }
    })


@scanner.route('/mobile-requisition-fulfillment/<int:requisition_id>')
@login_required
@admin_required  # Only SYS-Admin, WH-Admin, and Company-Admin can access
def mobile_requisition_fulfillment(requisition_id):
    """Mobile-optimized requisition fulfillment scanner route"""
    user_agent = request.headers.get('User-Agent', '')
    is_mobile = is_mobile_device(user_agent)
    
    if not is_mobile:
        # Return JSON response for API calls
        if request.headers.get('Accept') == 'application/json':
            return jsonify({
                'success': False,
                'message': 'Requisition fulfillment scanner is only available on mobile devices',
                'redirect': url_for('main.dashboard')
            }), 403
        
        # Redirect for browser requests
        flash('Requisition fulfillment scanner is only available on mobile devices.', 'warning')
        return redirect(url_for('requisitions.view_requisitions'))
    
    # Get the requisition
    requisition = Requisition.query.get_or_404(requisition_id)
    
    # Check if user has access to this requisition (based on company)
    # Allow SYS-Admin to access all requisitions
    if current_user.role != 'SYS-Admin' and current_user.company_id and requisition.company_id != current_user.company_id:
        flash('Access denied. You do not have permission to fulfill this requisition.', 'error')
        return redirect(url_for('requisitions.view_requisitions'))
    
    # Check if requisition is pending
    if requisition.status != 'Pending':
        flash('This requisition is not pending approval.', 'warning')
        return redirect(url_for('requisitions.view_requisitions'))
    
    # Prepare requisition items with FIFO batch recommendations
    items_with_batches = []
    for item in requisition.items:
        # Get all batches sorted by expiration date (FIFO)
        batches = sorted(item.product.warehouse_batches, key=lambda x: x.exp_date)
        # Filter out batches with no stock
        available_batches = [batch for batch in batches if batch.quantity > 0]
        
        # Calculate recommended batches based on FIFO logic
        recommended_batches = []
        remaining_qty = item.quantity
        
        for batch in available_batches:
            if remaining_qty <= 0:
                break
            
            # Calculate how much we need from this batch
            qty_needed = min(batch.quantity, remaining_qty)
            recommended_batches.append({
                'id': batch.id,
                'sub_barcode': batch.sub_barcode,
                'exp_date': batch.exp_date.strftime('%Y-%m-%d') if batch.exp_date else None,
                'quantity': batch.quantity,
                'qty_needed': qty_needed,
                'supplier_name': batch.supplier_name
            })
            
            remaining_qty -= qty_needed
        
        # Create a serializable representation of the item
        item_data = {
            'id': item.id,
            'product_id': item.product_id,
            'quantity': item.quantity,
            'uom': item.uom,
            'product_name': item.product.name
        }
        
        items_with_batches.append({
            'item': item_data,
            'recommended_batches': recommended_batches,
            'total_requested': item.quantity
        })
    
    # Set mobile-specific headers
    response = make_response(render_template(
        'warehouse/mobile_requisition_fulfillment.html', 
        current_user=current_user,
        requisition=requisition,
        items_with_batches=items_with_batches
    ))
    response.headers['X-Mobile-Only'] = 'true'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    
    return response


@scanner.route('/scan_requisition_batch', methods=['POST'])
@login_required
@admin_required
def scan_requisition_batch():
    """Scan a batch for requisition fulfillment and verify it matches FIFO recommendation"""
    try:
        data = request.get_json()
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Invalid JSON: {str(e)}'}), 400
    
    if not data:
        return jsonify({'status': 'error', 'message': 'No data received'}), 400
    
    requisition_id = data.get('requisition_id')
    product_id = data.get('product_id')
    scanned_sub_barcode = data.get('sub_barcode')
    quantity = float(data.get('quantity', 0)) if data.get('quantity') else 0
    
    # FIXED: Remove automatic barcode stripping to preserve leading zeros
    # Barcodes should be treated as exact strings without manipulation
    # The stripping logic has been removed to preserve barcode integrity
    
    if not all([requisition_id, product_id, scanned_sub_barcode]):
        missing_fields = []
        if not requisition_id:
            missing_fields.append('requisition_id')
        if not product_id:
            missing_fields.append('product_id')
        if not scanned_sub_barcode:
            missing_fields.append('sub_barcode')
        error_msg = f'Missing required fields: {", ".join(missing_fields)}'
        return jsonify({'status': 'error', 'message': error_msg}), 400

    try:
        # Get the requisition and item
        requisition = Requisition.query.get_or_404(requisition_id)
        requisition_item = None
        for item in requisition.items:
            if item.product_id == product_id:
                requisition_item = item
                break
        
        if not requisition_item:
            return jsonify({'status': 'error', 'message': 'Product not found in requisition'}), 404
        
        # Get the scanned batch using exact barcode match first
        batch = WarehouseProductBatch.query.filter_by(sub_barcode=scanned_sub_barcode).first()
        
        # If exact match fails, try alternative matching methods
        if not batch:
            # Try with leading zeros stripped (backward compatibility for older data)
            if scanned_sub_barcode.startswith('0'):
                stripped_barcode = scanned_sub_barcode.lstrip('0')
                batch = WarehouseProductBatch.query.filter_by(sub_barcode=stripped_barcode).first()
            
            # If still not found, try padding with zeros
            if not batch:
                # Try with leading zeros (up to 13 digits)
                padded_barcode = scanned_sub_barcode.zfill(13)
                if padded_barcode != scanned_sub_barcode:
                    batch = WarehouseProductBatch.query.filter_by(sub_barcode=padded_barcode).first()
        
        if not batch:
            return jsonify({'status': 'error', 'message': f'Batch not found for barcode: {scanned_sub_barcode}'}), 404
        
        # Verify the batch belongs to the correct product
        if batch.product_id != product_id:
            return jsonify({'status': 'error', 'message': 'Batch does not match the requested product'}), 400
        
        # Verify the batch has enough stock
        if batch.quantity < quantity:
            return jsonify({'status': 'error', 'message': f'Not enough stock in batch. Available: {batch.quantity}'}), 400
        
        # Get FIFO recommended batches for this product
        batches = sorted(requisition_item.product.warehouse_batches, key=lambda x: x.exp_date)
        available_batches = [b for b in batches if b.quantity > 0]
        
        # Check if the scanned batch is among the recommended FIFO batches
        is_fifo_compliant = False
        remaining_quantity = requisition_item.quantity
        recommended_quantity = 0
        
        # Check if the scanned batch is in the FIFO recommendation
        for recommended_batch in available_batches:
            if remaining_quantity <= 0:
                break
                
            qty_needed = min(recommended_batch.quantity, remaining_quantity)
            
            if recommended_batch.id == batch.id:
                is_fifo_compliant = True
                recommended_quantity = qty_needed
                break
                
            # Deduct quantity from this batch
            remaining_quantity -= qty_needed
        
        # If quantity was provided, validate it matches the requested quantity for this specific batch
        quantity_validation = None
        if quantity > 0:
            # Validate against the specific batch's required quantity, not the overall product quantity
            if abs(quantity - recommended_quantity) <= 0.001:  # Allow for small floating point differences
                quantity_validation = "valid"
            else:
                quantity_validation = "invalid"
        
        # Log the scan attempt
        log_activity(
            action="Requisition Batch Scan",
            details=f"Scanned batch <strong>{scanned_sub_barcode}</strong> for requisition <strong>#{requisition_id}</strong>. "
                    f"Product: <strong>{batch.product.name}</strong>, "
                    f"Quantity: <strong>{quantity if quantity > 0 else 'Not specified'} {batch.product.uom}</strong>, "
                    f"FIFO Compliant: <strong>{'Yes' if is_fifo_compliant else 'No'}</strong>"
        )
        
        response_data = {
            'status': 'success',
            'message': 'Batch scanned successfully',
            'is_fifo_compliant': is_fifo_compliant,
            'recommended_quantity': recommended_quantity,
            'batch_info': {
                'id': batch.id,
                'sub_barcode': batch.sub_barcode,
                'exp_date': batch.exp_date.strftime('%Y-%m-%d') if batch.exp_date else None,
                'quantity': batch.quantity,
                'product_name': batch.product.name,
                'uom': batch.product.uom,
                'product_id': batch.product_id  # Added product_id for consistency
            }
        }
        
        # Add quantity validation result if quantity was provided
        if quantity_validation:
            response_data['quantity_validation'] = quantity_validation
            if quantity_validation == "invalid":
                response_data['message'] = f'Quantity mismatch! Required for this batch: {recommended_quantity}, Scanned: {quantity}'
        
        return jsonify(response_data)
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@scanner.route('/fulfill_requisition_item', methods=['POST'])
@login_required
@admin_required
def fulfill_requisition_item():
    """Fulfill a requisition item by validating scanned batches (without deducting stock)"""
    try:
        data = request.get_json()
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Invalid JSON: {str(e)}'}), 400
    
    if not data:
        return jsonify({'status': 'error', 'message': 'No data received'}), 400
    
    requisition_id = data.get('requisition_id')
    product_id = data.get('product_id')
    scanned_batches = data.get('scanned_batches', [])  # List of {sub_barcode, quantity}
    
    # FIXED: Remove automatic barcode stripping to preserve leading zeros
    # Barcodes should be treated as exact strings without manipulation
    # The stripping logic has been removed to preserve barcode integrity
    
    if not all([requisition_id, product_id, scanned_batches]):
        missing_fields = []
        if not requisition_id:
            missing_fields.append('requisition_id')
        if not product_id:
            missing_fields.append('product_id')
        if not scanned_batches:
            missing_fields.append('scanned_batches')
        error_msg = f'Missing required fields: {", ".join(missing_fields)}'
        return jsonify({'status': 'error', 'message': error_msg}), 400

    try:
        # Get the requisition and item
        requisition = Requisition.query.get_or_404(requisition_id)
        requisition_item = None
        for item in requisition.items:
            if item.product_id == product_id:
                requisition_item = item
                break
        
        if not requisition_item:
            return jsonify({'status': 'error', 'message': 'Product not found in requisition'}), 404
        
        # Process each scanned batch for validation only
        validated_batches = []
        non_compliant_batches = []
        
        # Get recommended batches for validation
        batches = sorted(requisition_item.product.warehouse_batches, key=lambda x: x.exp_date)
        available_batches = [b for b in batches if b.quantity > 0]
        
        for scanned_batch in scanned_batches:
            sub_barcode = scanned_batch.get('sub_barcode')
            quantity = float(scanned_batch.get('quantity', 0))
            
            if not sub_barcode or quantity <= 0:
                continue
                
            # Get the batch using exact barcode match first
            batch = WarehouseProductBatch.query.filter_by(sub_barcode=sub_barcode).first()
            
            # If exact match fails, try normalized comparison for database compatibility
            if not batch:
                # Try to find with stripped version (for backward compatibility)
                stripped_barcode = sub_barcode[:12] if len(sub_barcode) > 12 else sub_barcode
                batch = WarehouseProductBatch.query.filter_by(sub_barcode=stripped_barcode).first()
            
            if not batch:
                return jsonify({'status': 'error', 'message': f'Batch {sub_barcode} not found'}), 404
            
            # Verify the batch belongs to the correct product
            if batch.product_id != product_id:
                return jsonify({'status': 'error', 'message': f'Batch {sub_barcode} does not match the requested product'}), 400
            
            # Verify the batch has enough stock
            if batch.quantity < quantity:
                return jsonify({
                    'status': 'error', 
                    'message': f'Not enough stock in batch {sub_barcode}. Available: {batch.quantity}, Requested: {quantity}'
                }), 400
            
            # Check if the batch is FIFO compliant and get the required quantity for this batch
            is_fifo_compliant = False
            batch_required_quantity = 0
            remaining_quantity = requisition_item.quantity
            
            # Check if the scanned batch is in the FIFO recommendation
            for recommended_batch in available_batches:
                if remaining_quantity <= 0:
                    break
                    
                qty_needed = min(recommended_batch.quantity, remaining_quantity)
                
                if recommended_batch.id == batch.id:
                    is_fifo_compliant = True
                    batch_required_quantity = qty_needed
                    break
                    
                # Deduct quantity from this batch
                deduct_amount = min(recommended_batch.quantity, remaining_quantity)
                remaining_quantity -= deduct_amount
            
            # Validate that the scanned quantity matches the required quantity for this specific batch
            if abs(quantity - batch_required_quantity) > 0.001:
                return jsonify({
                    'status': 'error',
                    'message': f'Quantity mismatch for batch {sub_barcode}! Required: {batch_required_quantity}, Scanned: {quantity}'
                }), 400
            
            if not is_fifo_compliant:
                non_compliant_batches.append({
                    'sub_barcode': sub_barcode,
                    'batch_id': batch.id
                })
            
            validated_batches.append({
                'batch_id': batch.id,
                'sub_barcode': batch.sub_barcode,
                'exp_date': batch.exp_date.strftime('%Y-%m-%d') if batch.exp_date else None,
                'scanned_quantity': quantity,
                'required_quantity': batch_required_quantity,  # Added required quantity for clarity
                'available_quantity': batch.quantity,
                'is_fifo_compliant': is_fifo_compliant
            })
        
        # If there are non-compliant batches, return error
        if non_compliant_batches:
            non_compliant_list = [b['sub_barcode'] for b in non_compliant_batches]
            return jsonify({
                'status': 'error',
                'message': f'Non-FIFO compliant batches detected: {", ".join(non_compliant_list)}. Please scan batches according to FIFO recommendation.'
            }), 400
        
        # Mark the requisition as validated
        requisition.validated = True
        db.session.commit()
        
        # Mark the requisition as validated
        requisition.validated = True
        db.session.commit()
        
        # Check if this is a partial fulfillment (single batch with less than total quantity)
        is_partial = len(scanned_batches) == 1 and quantity < requisition_item.quantity
        
        # Log the validation
        if is_partial:
            log_activity(
                action="Requisition Batch Validated",
                details=f"Validated batch <strong>{validated_batches[0]['sub_barcode']}</strong> for requisition item <strong>{requisition_item.product.name}</strong> for requisition <strong>#{requisition_id}</strong>. "
                        f"Quantity: <strong>{quantity} {requisition_item.uom}</strong>"
            )
        else:
            log_activity(
                action="Requisition Item Validated",
                details=f"Validated requisition item <strong>{requisition_item.product.name}</strong> for requisition <strong>#{requisition_id}</strong>. "
                        f"Total quantity: <strong>{requisition_item.quantity} {requisition_item.uom}</strong> from <strong>{len(validated_batches)}</strong> batches."
            )
        
        return jsonify({
            'status': 'success',
            'message': f'Requisition {"batch" if is_partial else "item"} validated successfully!',
            'validated_batches': validated_batches,
            'is_partial': is_partial
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@scanner.route('/api/pending-requisitions')
@login_required
@admin_required
def api_pending_requisitions():
    """API endpoint to fetch pending requisitions for mobile scanner"""
    try:
        # Get pending requisitions for the current user's company
        if current_user.role == 'SYS-Admin':
            # SYS-Admin can see all pending requisitions
            pending_requisitions = Requisition.query.filter_by(status='Pending').order_by(Requisition.date_created.desc()).all()
        else:
            # Other admins can only see pending requisitions from their company
            pending_requisitions = Requisition.query.filter_by(
                status='Pending',
                company_id=current_user.company_id
            ).order_by(Requisition.date_created.desc()).all()
        
        # Format the data for JSON response
        requisitions_data = []
        for req in pending_requisitions:
            requisitions_data.append({
                'id': req.id,
                'requested_by': req.requested_by,
                'branch': req.branch,
                'date_created': req.date_created.strftime('%Y-%m-%d %H:%M'),
                'status': req.status,
                'validated': req.validated,
                'items_count': len(req.items)
            })
        
        return jsonify({
            'success': True,
            'requisitions': requisitions_data,
            'count': len(requisitions_data)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error fetching pending requisitions: {str(e)}'
        }), 500


@scanner.route('/api/update-requisition-status', methods=['POST'])
@login_required
@admin_required
def api_update_requisition_status():
    """API endpoint to update requisition status (validate, approve, decline)"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data received'}), 400
        
        requisition_id = data.get('requisition_id')
        action = data.get('action')  # 'validate', 'approve', 'decline'
        
        if not all([requisition_id, action]):
            return jsonify({'success': False, 'message': 'Missing required fields'}), 400
        
        # Get the requisition
        requisition = Requisition.query.get_or_404(requisition_id)
        
        # Check if user has access to this requisition
        if current_user.role != 'SYS-Admin' and requisition.company_id != current_user.company_id:
            return jsonify({'success': False, 'message': 'Access denied'}), 403
        
        if action == 'validate':
            # Mark as validated
            requisition.validated = True
            db.session.commit()
            log_activity(
                action="Requisition Validated",
                details=f"Requisition <strong>#{requisition.id}</strong> validated by <strong>{current_user.full_name}</strong>"
            )
            return jsonify({'success': True, 'message': 'Requisition validated successfully'})
        
        elif action == 'approve':
            # Check if requisition is validated
            if not requisition.validated:
                return jsonify({'success': False, 'message': 'Requisition must be validated before approval'}), 400
            
            # Handle stock deduction only if currently pending
            if requisition.status == 'Pending':
                for req_item in requisition.items:
                    product = req_item.product
                    remaining_quantity = req_item.quantity  # How much we still need to deduct

                    if product.warehouse_qty < req_item.quantity:
                        return jsonify({'success': False, 'message': f'Error: Not enough warehouse stock for {product.name}. Requested: {req_item.quantity}, Available in warehouse: {product.warehouse_qty}'}), 400

                    # Store the total current quantity before any deduction
                    total_before_deduction = product.quantity
                    warehouse_before = product.warehouse_qty

                    # Get all batches sorted by expiration date (first)
                    batches = sorted(product.warehouse_batches, key=lambda x: x.exp_date)

                    # Track which batches were updated for logging
                    updated_batches = []

                    # Deduct from batches starting with expiry
                    for batch in batches:
                        if remaining_quantity <= 0:
                            break

                        if batch.quantity > 0:  # Only use batches that have stock
                            deduct_amount = min(batch.quantity, remaining_quantity)
                            batch.quantity = batch.quantity - deduct_amount
                            remaining_quantity -= deduct_amount
                            updated_batches.append({
                                'batch_id': batch.id,
                                'exp_date': batch.exp_date.strftime('%Y-%m-%d'),
                                'deducted': deduct_amount,
                                'remaining': batch.quantity
                            })

                    # Transfer from warehouse to store
                    product.warehouse_qty -= req_item.quantity
                    product.store_qty += req_item.quantity
                    product.store_initial_qty = product.store_qty
                    # Update legacy total quantity
                    product.quantity = product.warehouse_qty + product.store_qty

                    # Store deduction summary (not per-batch details)
                    db.session.add(
                        RequisitionBatchDeduction(
                            requisition_item_id=req_item.id,
                            total_current_qty=warehouse_before,
                            requested_qty=req_item.quantity,
                            remaining_qty=product.warehouse_qty
                        )
                    )

                    # Create ProductHistory record for TRANS OUT
                    history_record = ProductHistory(
                        product_id=req_item.product_id,
                        trxn_date=datetime.now(ZoneInfo("Asia/Manila")),
                        trxn_code='TRANS OUT',
                        payee=requisition.branch or 'Unknown',  # branch now contains franchise name
                        quantity_in=0.0,
                        quantity_out=req_item.quantity,
                        net_change=-req_item.quantity,
                        reference_id=requisition.id,
                        reference_type='requisition'
                    )
                    # Assign company_id to the history record
                    history_record = assign_company(history_record)
                    db.session.add(history_record)

                    # Record warehouse release quantity
                    req_item.released_quantity = req_item.quantity
                    rec = ReceivingRecord.query.filter_by(
                        requisition_item_id=req_item.id,
                        requisition_id=requisition.id
                    ).first()
                    if not rec:
                        rec = ReceivingRecord(
                            requisition_item_id=req_item.id,
                            requisition_id=requisition.id,
                            released_qty=req_item.quantity,
                            received_qty=0.0,
                            variance_qty=-req_item.quantity,
                            variance_type='short',
                            company_id=requisition.company_id,
                            status='pending'
                        )
                        db.session.add(rec)
                    else:
                        rec.released_qty = req_item.quantity

            # Update status to approved and set approval date
            requisition.status = 'approved'
            requisition.date_approved = datetime.now(ZoneInfo("Asia/Manila"))
            db.session.commit()
            log_activity(
                action="Requisition Approved",
                details=f"Requisition <strong>#{requisition.id}</strong> approved by <strong>{current_user.full_name}</strong>"
            )
            # Notify requester
            try:
                req_user = User.query.filter_by(full_name=requisition.requested_by, company_id=requisition.company_id).first()
                if req_user:
                    create_notification(
                        user_id=req_user.id,
                        title=f'Requisition #{requisition.id} Approved',
                        message=f'Your requisition has been approved.',
                        type='success',
                        reference_type='requisition',
                        reference_id=requisition.id
                    )
            except Exception:
                pass
            return jsonify({'success': True, 'message': 'Requisition approved successfully'})
        
        elif action == 'decline':
            # Update status to declined
            requisition.status = 'declined'
            db.session.commit()
            log_activity(
                action="Requisition Declined",
                details=f"Requisition <strong>#{requisition.id}</strong> declined by <strong>{current_user.full_name}</strong>"
            )
            # Notify requester
            try:
                req_user = User.query.filter_by(full_name=requisition.requested_by, company_id=requisition.company_id).first()
                if req_user:
                    create_notification(
                        user_id=req_user.id,
                        title=f'Requisition #{requisition.id} Declined',
                        message=f'Your requisition has been declined.',
                        type='danger',
                        reference_type='requisition',
                        reference_id=requisition.id
                    )
            except Exception:
                pass
            return jsonify({'success': True, 'message': 'Requisition declined successfully'})
        
        else:
            return jsonify({'success': False, 'message': 'Invalid action'}), 400
            
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error updating requisition: {str(e)}'}), 500


@scanner.route('/mobile-pending-requisitions')
@login_required
@admin_required  # Only SYS-Admin, WH-Admin, and Company-Admin can access
def mobile_pending_requisitions():
    """Mobile-optimized pending requisitions view route"""
    user_agent = request.headers.get('User-Agent', '')
    is_mobile = is_mobile_device(user_agent)
    
    if not is_mobile:
        # Return JSON response for API calls
        if request.headers.get('Accept') == 'application/json':
            return jsonify({
                'success': False,
                'message': 'Pending requisitions view is only available on mobile devices',
                'redirect': url_for('main.dashboard')
            }), 403
        
        # Redirect for browser requests
        flash('Pending requisitions view is only available on mobile devices.', 'warning')
        return redirect(url_for('requisitions.view_requisitions'))
    
    # Set mobile-specific headers
    response = make_response(render_template('warehouse/mobile_pending_requisitions.html', current_user=current_user))
    response.headers['X-Mobile-Only'] = 'true'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    
    return response


@scanner.route('/mobile-batch-sub-audit')
@login_required
@admin_required  # Only SYS-Admin, WH-Admin, and Company-Admin can access
def mobile_batch_sub_audit():
    """Mobile-optimized batch sub barcode audit route"""
    user_agent = request.headers.get('User-Agent', '')
    is_mobile = is_mobile_device(user_agent)
    
    if not is_mobile:
        # Return JSON response for API calls
        if request.headers.get('Accept') == 'application/json':
            return jsonify({
                'success': False,
                'message': 'Mobile batch sub audit is only available on mobile devices',
                'redirect': url_for('main.dashboard')
            }), 403
        
        # Redirect for browser requests
        flash('Mobile batch sub audit is only available on mobile devices.', 'warning')
        return redirect(url_for('main.dashboard'))
    
    # Set mobile-specific headers
    response = make_response(render_template('warehouse/mobile_batch_sub_audit.html', current_user=current_user))
    response.headers['X-Mobile-Only'] = 'true'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    
    return response


@scanner.route('/batch-audit-pending')
@login_required
@admin_required  # Only SYS-Admin, WH-Admin, and Company-Admin can access
def batch_audit_pending():
    """Batch audit pending list route"""
    user_agent = request.headers.get('User-Agent', '')
    is_mobile = is_mobile_device(user_agent)
    
    if not is_mobile:
        # Return JSON response for API calls
        if request.headers.get('Accept') == 'application/json':
            return jsonify({
                'success': False,
                'message': 'Batch audit pending list is only available on mobile devices',
                'redirect': url_for('main.dashboard')
            }), 403
        
        # Redirect for browser requests
        flash('Batch audit pending list is only available on mobile devices.', 'warning')
        return redirect(url_for('main.dashboard'))
    
    try:
        # Get pending batch audits (status = 'pending') grouped by batch_label
        pending_audits = BatchAudit.query.filter_by(status='pending').order_by(BatchAudit.audit_timestamp.desc()).all()
        
        # Group audits by batch_label
        grouped_audits = {}
        for audit in pending_audits:
            batch_label = audit.batch_label or 'Unknown'
            if batch_label not in grouped_audits:
                grouped_audits[batch_label] = []
            grouped_audits[batch_label].append(audit)
        
        # Set mobile-specific headers
        response = make_response(render_template('warehouse/batch_audit_pending.html', 
                                               grouped_audits=grouped_audits, 
                                               current_user=current_user))
        response.headers['X-Mobile-Only'] = 'true'
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        
        return response
    except Exception as e:
        flash(f'Error loading pending batch audits: {str(e)}', 'error')
        return redirect(url_for('scanner.mobile_scanner'))


@scanner.route('/api/products-with-batches')
@login_required
@admin_required
def api_products_with_batches():
    """API endpoint to fetch products with batches for mobile batch sub audit"""
    try:
        # Get products with batches for the current user's company
        # For SYS-Admin users, allow access to all products regardless of company
        if current_user.role == 'SYS-Admin' and current_user.company_id is None:
            # SYS-Admin with no company can see all products
            products = Product.query.join(WarehouseProductBatch).filter(
                Product.id == WarehouseProductBatch.product_id
            ).order_by(Product.name).all()
        else:
            # For other users, check only in their company
            products = Product.query.join(WarehouseProductBatch).filter(
                Product.id == WarehouseProductBatch.product_id,
                Product.company_id == current_user.company_id
            ).order_by(Product.name).all()
        
        # Format the data for JSON response
        products_data = []
        for product in products:
            # Get batches for this product
            batches = WarehouseProductBatch.query.filter_by(product_id=product.id).all()
            
            # Only include products that have batches (even if batch quantity is 0)
            if batches:
                batch_data = []
                for batch in batches:
                    batch_data.append({
                        'id': batch.id,
                        'exp_date': batch.exp_date.strftime('%Y-%m-%d') if batch.exp_date else None,
                        'quantity': batch.quantity,
                        'sub_barcode': batch.sub_barcode
                    })
                
                products_data.append({
                    'id': product.id,
                    'name': product.name,
                    'uom': product.uom,
                    'batches': batch_data
                })
        
        return jsonify({
            'success': True,
            'products': products_data
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error fetching products with batches: {str(e)}'
        }), 500
