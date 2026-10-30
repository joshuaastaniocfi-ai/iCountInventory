# Standard library imports
from datetime import datetime, timedelta
import csv
import io
import os
import calendar
from zoneinfo import ZoneInfo

# Third-party imports
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, Response, current_app
from flask_login import login_required, current_user
import openpyxl
from openpyxl import load_workbook
from barcode import get_barcode_class
from barcode.writer import ImageWriter
from sqlalchemy import or_

# Local imports
from extensions import db
from models import Product, WarehouseProductBatch, StoreProductBatch, ProductHistory, Requisition, RequisitionItem, Company, PendingRemoval, StockAudit, DeletionRequest, Notification, User
from helpers import user_redirect_to_requisition, admin_required, sys_admin_required, edit_delete_required, generate_barcode, generate_sub_barcode, log_activity, assign_company, ensure_product_barcode, generate_barcode_image

# Create blueprint with URL prefix as required by project specifications
products = Blueprint('products', __name__, url_prefix='/products')


def add_months_to_date(value, months):
    """Add calendar months while keeping end-of-month dates valid."""
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


@products.route('/add_product', methods=['GET'])
@login_required
@user_redirect_to_requisition
@admin_required
def add_product_page():
    """Display the add product page"""
    # Get unique account titles for the current user's company
    if current_user.company_id:
        account_titles = db.session.query(Product.account_title).filter(
            Product.company_id == current_user.company_id
        ).distinct().order_by(Product.account_title).all()
    else:
        # For SYS-Admin with no company, get all account titles
        account_titles = db.session.query(Product.account_title).distinct().order_by(Product.account_title).all()
    
    account_titles = [title[0] for title in account_titles]
    
    if current_user.company_id:
        stations_query = db.session.query(Product.station).filter(
            Product.company_id == current_user.company_id,
            Product.station.isnot(None),
            Product.station != ''
        ).distinct().order_by(Product.station).all()
    else:
        stations_query = db.session.query(Product.station).filter(
            Product.station.isnot(None),
            Product.station != ''
        ).distinct().order_by(Product.station).all()
    stations = [s[0] for s in stations_query if s[0]]
    
    # Create a minimal pagination object to prevent template errors
    from collections import namedtuple
    Pagination = namedtuple('Pagination', ['pages', 'total'])
    pagination = Pagination(pages=0, total=0)
    
    stations_query = db.session.query(Product.station).filter(Product.station.isnot(None), Product.station != '').distinct().order_by(Product.station).all()
    stations = [s[0] for s in stations_query if s[0]]
    return render_template('shared/products.html', account_titles=account_titles, stations=stations, pagination=pagination)


@products.route('/products', methods=['GET'], endpoint='legacy_products_path')
def legacy_products_path():
    """Redirect the old duplicated products URL to its canonical route."""
    return redirect(url_for('products.view_products'), code=301)


@products.route('', methods=['GET'])
@login_required
@user_redirect_to_requisition
def view_products():
    """Display the products page with filtering and pagination"""
    # Check if user has permission to view products
    if current_user.role not in ['SYS-Admin', 'WH-Admin', 'Company-Admin', 'Purchaser']:
        flash('Access denied. You do not have permission to view products.', 'error')
        return redirect(url_for('main.dashboard'))
    # Get query parameters
    page = request.args.get('page', 1, type=int)
    search_query = request.args.get('q', '').strip()
    account_type = request.args.get('account_type', '').strip()
    station_filter = request.args.get('station', '').strip()
    status_filter = request.args.get('status', '').strip()
    company_id = request.args.get('company_id', '').strip()
    
    # Base query - filter by current user's company or handled companies
    user_comps = current_user.all_companies if hasattr(current_user, 'all_companies') else []
    can_filter_companies = (current_user.role == 'SYS-Admin' and current_user.company_id is None) or len(user_comps) > 1

    if can_filter_companies:
        companies = Company.query.order_by(Company.name.asc()).all() if current_user.role == 'SYS-Admin' else user_comps
        if company_id:
            try:
                cid = int(company_id)
                query = Product.query.filter_by(company_id=cid)
            except (ValueError, TypeError):
                query = Product.query.filter_by(company_id=current_user.company_id)
        else:
            if current_user.role == 'SYS-Admin' and current_user.company_id is None:
                query = Product.query
            else:
                query = Product.query.filter_by(company_id=current_user.company_id)
    else:
        query = Product.query.filter_by(company_id=current_user.company_id)
        companies = None
    
    # Apply search filter
    if search_query:
        search_filter = or_(
            Product.name.ilike(f'%{search_query}%'),
            Product.barcode.ilike(f'%{search_query}%'),
            Product.item_uom_desc.ilike(f'%{search_query}%')
        )
        query = query.filter(search_filter)
    
    # Apply account title filter
    if account_type:
        query = query.filter(Product.account_title == account_type)
    
    # Apply station filter
    if station_filter:
        query = query.filter(Product.station == station_filter)
    
    # Apply status filter
    if status_filter:
        if status_filter == 'OK':
            query = query.filter(
                Product.quantity > 0,
                db.or_(
                    db.and_(Product.reorder_level > 0, Product.quantity > Product.reorder_level),
                    db.and_(Product.reorder_level == 0, Product.initial_quantity > 0, 
                           Product.quantity > (Product.initial_quantity * (Product.low_stock_threshold / 100)))
                )
            )
        elif status_filter == 'Low Stock':
            query = query.filter(
                Product.quantity > 0,
                db.or_(
                    db.and_(Product.reorder_level > 0, Product.quantity <= Product.reorder_level),
                    db.and_(Product.reorder_level == 0, Product.initial_quantity > 0, 
                           Product.quantity <= (Product.initial_quantity * (Product.low_stock_threshold / 100)))
                )
            )
        elif status_filter == 'No Stock':
            query = query.filter(Product.quantity == 0)
        elif status_filter == 'Expiring Soon':
            # Products with batches expiring within 30 days
            today = datetime.now(ZoneInfo("Asia/Manila")).date()
            thirty_days = today + timedelta(days=30)
            query = query.join(WarehouseProductBatch).filter(
                WarehouseProductBatch.exp_date.between(today, thirty_days),
                WarehouseProductBatch.quantity > 0
            ).distinct()
        elif status_filter == 'Expiring 3 Months':
            # Products with batches expiring within 3 months (31-90 days)
            today = datetime.now(ZoneInfo("Asia/Manila")).date()
            thirty_days = today + timedelta(days=30)
            ninety_days = today + timedelta(days=90)
            query = query.join(WarehouseProductBatch).filter(
                WarehouseProductBatch.exp_date.between(thirty_days, ninety_days),
                WarehouseProductBatch.quantity > 0
            ).distinct()
        elif status_filter == 'Expired':
            # Products with expired batches
            today = datetime.now(ZoneInfo("Asia/Manila")).date()
            query = query.join(WarehouseProductBatch).filter(
                WarehouseProductBatch.exp_date < today,
                WarehouseProductBatch.quantity > 0
            ).distinct()
        elif status_filter == 'Favorites':
            query = query.filter(Product.is_favorite.is_(True))
    
    # Get unique account titles for the filter dropdown
    if current_user.company_id:
        account_titles = db.session.query(Product.account_title).filter(
            Product.company_id == current_user.company_id
        ).distinct().order_by(Product.account_title).all()
    else:
        # For SYS-Admin with no company, get all account titles
        account_titles = db.session.query(Product.account_title).distinct().order_by(Product.account_title).all()
    
    account_titles = [title[0] for title in account_titles]
    
    # Get unique stations for the filter dropdown
    if current_user.company_id:
        stations_query = db.session.query(Product.station).filter(
            Product.company_id == current_user.company_id,
            Product.station.isnot(None),
            Product.station != ''
        ).distinct().order_by(Product.station).all()
    else:
        stations_query = db.session.query(Product.station).filter(
            Product.station.isnot(None),
            Product.station != ''
        ).distinct().order_by(Product.station).all()
    stations = [s[0] for s in stations_query if s[0]]
    
    # Order by name and paginate
    query = query.order_by(Product.name)
    pagination = query.paginate(page=page, per_page=20, error_out=False)
    products = pagination.items
    
    # Pass query string for pagination links
    query_params = request.args.copy()
    if 'page' in query_params:
        del query_params['page']
    query_string = '&'.join([f"{key}={value}" for key, value in query_params.items()])
    
    return render_template('shared/products.html', 
                         products=products,
                         pagination=pagination,
                         account_titles=account_titles,
                         stations=stations,
                         query_string=query_string,
                         companies=companies,
                         now=datetime.now(ZoneInfo("Asia/Manila")))


@products.route('/add_product', methods=['POST'])
@login_required
@user_redirect_to_requisition
@admin_required
def add_product():
    """Add a new product"""
    try:
        # Debug: Print form data to see what's being received
        print("Form data received:")
        for key, value in request.form.items():
            print(f"  {key}: {value}")
        
        # Get form data
        name = request.form['name'].strip()
        account_title = request.form['account_title'].strip()
        item_uom_desc = request.form.get('item_uom_desc', '').strip()
        uom_conversion = request.form.get('uom_conversion', '1').strip()
        uom = request.form['uom'].strip()
        quantity = float(request.form.get('quantity', 0))
        # Use quantity as initial_quantity since that's what the form provides
        initial_quantity = quantity
        low_stock_threshold = int(request.form.get('low_stock_threshold', 
            current_app.config.get('LOW_STOCK_THRESHOLD_DEFAULT', 10)))
        reorder_level = int(request.form.get('reorder_level', 0))  # Get reorder level from form
        exp_date = request.form.get('exp_date', '').strip()
        purchase_order_place = request.form.get('purchase_order_place', '').strip()
        
        # Debug: Print parsed values
        print(f"Parsed values: name={name}, account_title={account_title}, uom={uom}, quantity={quantity}")
        
        # Validate required fields
        if not name or not account_title or not uom:
            flash('Name, Account Title, and UOM are required', 'error')
            print("Validation failed: Required fields missing")
            return redirect(url_for('products.view_products'))
        
        # UOM conversion should be treated as text, not converted to float
        # If empty, default to '1' as per project specification
        if not uom_conversion:
            uom_conversion = '1'
        
        # Generate unique barcode
        barcode = generate_barcode()
        print(f"Generated barcode: {barcode}")
        
        # Create new product with company assignment
        product = Product(
            barcode=barcode,
            name=name,
            account_title=account_title,
            item_uom_desc=item_uom_desc,
            uom_conversion=uom_conversion,  # Keep as string, don't convert to float
            uom=uom,
            quantity=quantity,
            initial_quantity=initial_quantity,
            warehouse_qty=quantity,
            warehouse_initial_qty=initial_quantity,
            store_qty=0,
            store_initial_qty=0,
            low_stock_threshold=low_stock_threshold,
            reorder_level=reorder_level,  # Add reorder level to product
            exp_date=exp_date if exp_date else None,
            purchase_order_place=purchase_order_place
        )
        
        # Assign to current user's company
        product = assign_company(product)
        ensure_product_barcode(product)
        print(f"Assigned company: {product.company_id}")
        
        # Add to database
        db.session.add(product)
        db.session.flush()  # Flush to get the product ID
        print(f"Product added to session with ID: {product.id}")
        
        # Create ProductHistory record for TRANS IN (initial stock)
        if quantity > 0:
            current_time = datetime.now(ZoneInfo("Asia/Manila"))
            # Payee should include both product's purchase_order_place when available
            payee = purchase_order_place or 'Initial Stock'
            history_record = ProductHistory(
                product_id=product.id,
                trxn_date=current_time,
                trxn_code='TRANS IN',
                payee=payee,
                quantity_in=quantity,
                quantity_out=0.0,
                net_change=quantity,
                reference_id=None,  # No specific reference for initial stock
                reference_type='initial'
            )
            # Assign company to history record
            history_record = assign_company(history_record)
            db.session.add(history_record)
            print("ProductHistory record added")
        
        db.session.commit()
        print("Database commit successful")
        
        # If product has expiration date, create initial batch
        if exp_date:
            try:
                # Parse the expiration date
                exp_date_obj = datetime.strptime(exp_date, '%Y-%m-%d').date()
                
                # Create initial batch with sub-barcode
                batch = WarehouseProductBatch(
                    product_id=product.id,
                    quantity=quantity,
                    int_quantity=initial_quantity,
                    exp_date=exp_date_obj,
                    supplier_name=purchase_order_place if purchase_order_place else 'Initial Stock',
                    sub_barcode=None
                )
                db.session.add(batch)
                db.session.commit()
                
                flash(f'Product "{name}" added successfully with initial batch!', 'success')
                print(f'Product "{name}" added successfully with initial batch!')
            except ValueError as e:
                flash(f'Product "{name}" added, but failed to create initial batch due to invalid date format', 'warning')
                print(f"Batch creation failed: {e}")
                db.session.rollback()
        else:
            flash(f'Product "{name}" added successfully!', 'success')
            print(f'Product "{name}" added successfully!')
        
        # Log the activity
        log_activity(
            action="Product Added",
            details=f"Added product: {name} (Barcode: {barcode})"
        )
        print("Activity logged")
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error adding product: {str(e)}', 'error')
        print(f"Exception occurred: {str(e)}")
        log_activity(
            action="Product Add Error",
            details=f"Failed to add product: {str(e)}"
        )
    
    return redirect(url_for('products.view_products'))


@products.route('/edit_product/<int:product_id>', methods=['POST'])
@login_required
@edit_delete_required
def edit_product(product_id):
    """Update product details without changing stock quantities or batches."""
    try:
        if current_user.role == 'SYS-Admin' and current_user.company_id is None:
            product = Product.query.get(product_id)
        else:
            product = Product.query.filter_by(
                id=product_id,
                company_id=current_user.company_id
            ).first()

        if not product:
            flash('Product not found or access denied', 'error')
            return redirect(url_for('products.view_products'))

        name = request.form.get('name', '').strip()
        account_title = request.form.get('account_title', '').strip()
        uom = request.form.get('uom', '').strip()
        if not name or not account_title or not uom:
            flash('Name, Account Title, and UOM are required', 'error')
            return redirect(url_for('products.view_products'))

        product.name = name
        product.account_title = account_title
        product.item_uom_desc = request.form.get('item_uom_desc', '').strip()
        product.uom_conversion = request.form.get('uom_conversion', '1').strip() or '1'
        product.uom = uom
        product.low_stock_threshold = int(request.form.get('low_stock_threshold', 10))
        product.reorder_level = int(request.form.get('reorder_level', 0))
        product.exp_date = request.form.get('exp_date', '').strip() or None
        product.purchase_order_place = request.form.get('purchase_order_place', '').strip()

        db.session.commit()
        log_activity(
            action='Product Edited',
            details=f'Updated product: {product.name} (Barcode: {product.barcode})'
        )
        flash(f'Product "{product.name}" updated successfully', 'success')
    except (TypeError, ValueError) as e:
        db.session.rollback()
        flash(f'Invalid product details: {str(e)}', 'error')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating product: {str(e)}', 'error')

    return redirect(url_for('products.view_products'))


@products.route('/add_batch', methods=['POST'])
@login_required
@user_redirect_to_requisition
@admin_required
def add_batch():
    data = request.get_json()
    product_id = data.get('product_id')
    quantity = float(data.get('quantity'))
    exp_date_str = data.get('exp_date')
    supplier_name = data.get('supplier_name')


    if not all([product_id, quantity, exp_date_str]):
        return {'status': 'error', 'message': 'Missing required fields'}, 400

    try:
        exp_date = datetime.strptime(exp_date_str, '%Y-%m-%d').date()
        
        # Check if product exists and belongs to the user's company
        product = Product.query.filter_by(
            id=product_id,
            company_id=current_user.company_id
        ).first()

        if not product:
            return {'status': 'error', 'message': 'Product not found'}, 404

        # Create new batch with sub-barcode
        new_batch = WarehouseProductBatch(
            product_id=product_id,
            quantity=quantity,
            int_quantity=quantity,
            exp_date=exp_date,
            supplier_name=supplier_name,

            sub_barcode=None
        )

        db.session.add(new_batch)
        db.session.flush()  # Flush to get the batch ID

        # Create ProductHistory record for TRANS IN (batch addition)
        current_time = datetime.now(ZoneInfo("Asia/Manila"))
        # Payee should include both product's purchase_order_place and batch's supplier_name when available
        payee = format_payee_for_transaction(product, supplier_name)
        
        history_record = ProductHistory(
            product_id=product_id,
            trxn_date=current_time,
            trxn_code='TRANS IN',
            payee=payee,
            quantity_in=quantity,
            quantity_out=0.0,
            net_change=quantity,
            reference_id=new_batch.id,
            reference_type='batch',
            company_id=product.company_id
        )
        db.session.add(history_record)

        db.session.commit()

        log_activity(
            action="Add Batch",
            details=f"Added new batch to <strong>{product.name}</strong> with "
                    f"quantity <span class='badge bg-info'>{quantity} {product.uom}</span>, "
                    f"expires: <strong>{exp_date}</strong>, "
                    f"supplier: <strong>{supplier_name or 'N/A'}</strong>"
        )

        return {'status': 'success', 'message': 'Batch added successfully'}

    except Exception as e:
        db.session.rollback()
        return {'status': 'error', 'message': str(e)}, 500


@products.route('/delete_batch', methods=['POST'])
@login_required
@user_redirect_to_requisition
@edit_delete_required
def delete_batch():
    data = request.get_json()
    product_id = data.get('product_id')
    batch_id = data.get('batch_id')

    if not all([product_id, batch_id]):
        return {'status': 'error', 'message': 'Missing required fields'}, 400

    # Convert to integers to ensure proper type matching
    try:
        product_id = int(product_id)
        batch_id = int(batch_id)
    except (ValueError, TypeError):
        return {'status': 'error', 'message': 'Invalid product_id or batch_id format'}, 400

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
            return {'status': 'error', 'message': 'Batch not found'}, 404

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
            return {'status': 'error', 'message': 'Product not found'}, 404

        # Check if batch is referenced in any pending removals (approved, rejected, or pending)
        pending_removals = PendingRemoval.query.filter_by(batch_id=batch_id).all()
        if pending_removals:
            # Remove the references to this batch in pending removals
            for removal in pending_removals:
                db.session.delete(removal)
            db.session.flush()  # Flush to remove the references

        # Update product quantities (warehouse stock)
        product.warehouse_qty -= batch.quantity
        if product.warehouse_qty < 0:
            product.warehouse_qty = 0
        product.quantity = product.warehouse_qty + product.store_qty

        # Log before deleting
        log_activity(
            action="Delete Batch",
            details=f"Deleted batch from <strong>{product.name}</strong> with "
                    f"quantity <span class='badge bg-info'>{batch.quantity} {product.uom}</span>, "
                    f"expiry: <strong>{batch.exp_date}</strong>"
        )

        db.session.delete(batch)
        db.session.commit()

        return {'status': 'success', 'message': 'Batch deleted successfully'}

    except Exception as e:
        db.session.rollback()
        return {'status': 'error', 'message': str(e)}, 500


def format_payee_for_transaction(product, supplier_name=None):
    """
    Format the payee field for a transaction based on product and supplier information.
    
    Args:
        product: Product object
        supplier_name: Supplier name string (optional)
        
    Returns:
        str: Formatted payee string
    """
    payee_parts = []
    if product.purchase_order_place:
        payee_parts.append(product.purchase_order_place)
    if supplier_name:
        payee_parts.append(supplier_name)
    
    # If neither is available, use a default value
    return " - ".join(payee_parts) if payee_parts else 'Manual Addition'


@products.route('/update_batch', methods=['POST'])
@login_required
@user_redirect_to_requisition
@edit_delete_required
def update_batch():
    """Update batch metadata like expiration date and supplier name (Admin only)."""
    data = request.get_json() or {}
    product_id = data.get('product_id')
    batch_id = data.get('batch_id')
    exp_date_str = data.get('exp_date')
    supplier_name = data.get('supplier_name')

    new_quantity_str = data.get('quantity')

    if not all([product_id, batch_id]):
        return jsonify({'status': 'error', 'message': 'Missing required fields'}), 400

    # Normalize types
    try:
        product_id = int(product_id)
        batch_id = int(batch_id)
    except (ValueError, TypeError):
        return jsonify({'status': 'error', 'message': 'Invalid product_id or batch_id format'}), 400

    try:
        # SYS-Admin with no company can edit batches for any product
        if current_user.role == 'SYS-Admin' and current_user.company_id is None:
            product = Product.query.get(product_id)
        else:
            product = Product.query.filter_by(
                id=product_id,
                company_id=current_user.company_id
            ).first()
        
        if not product:
            return jsonify({'status': 'error', 'message': 'Product not found'}), 404

        # Check if batch exists and belongs to the user's company
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
            return jsonify({'status': 'error', 'message': 'Batch not found for this product'}), 404

        # Determine if product is supplies (non-expiring allowed)
        supplies_categories = ['Supplies-Kitchen', 'Supplies-Packaging', 'Supplies-Store Dining', 'Supplies-Store Office', 'Supplies-Utility']
        is_supplies_product = product.account_title in supplies_categories or product.account_title.lower().startswith('supplies')

        # Parse/validate new expiration date
        new_exp_date = None
        if exp_date_str:
            try:
                new_exp_date = datetime.strptime(exp_date_str, '%Y-%m-%d').date()
            except ValueError:
                return jsonify({'status': 'error', 'message': 'Invalid date format. Use YYYY-MM-DD'}), 400
        else:
            # Allow blank for supplies (set to far-future)
            if is_supplies_product:
                new_exp_date = datetime(2099, 12, 31).date()
            else:
                return jsonify({'status': 'error', 'message': 'Expiry date is required for non-Supplies products'}), 400

        # Keep old values for logging
        old_exp_date = batch.exp_date
        old_supplier = batch.supplier_name
        old_quantity = batch.quantity

        # Apply updates
        batch.exp_date = new_exp_date
        batch.supplier_name = supplier_name

        
        
        # If quantity provided, validate and update
        if new_quantity_str is not None and new_quantity_str != '':
            try:
                new_quantity = float(new_quantity_str)
            except ValueError:
                return jsonify({'status': 'error', 'message': 'Invalid quantity format'}), 400
            if new_quantity < 0:
                return jsonify({'status': 'error', 'message': 'Quantity must be non-negative'}), 400
            batch.quantity = new_quantity

        # Recalculate product warehouse quantity from all batches and sync total
        all_batches = WarehouseProductBatch.query.filter_by(product_id=product_id).all()
        total_wh = sum(b.quantity for b in all_batches)
        product.warehouse_qty = total_wh
        product.warehouse_initial_qty = max(product.warehouse_initial_qty or 0, total_wh)
        product.quantity = product.warehouse_qty + product.store_qty
        product.initial_quantity = product.warehouse_initial_qty + (product.store_initial_qty or 0)
        product.last_updated = datetime.now(ZoneInfo("Asia/Manila"))

        # If supplier name changed, update the payee field in ProductHistory records
        if old_supplier != supplier_name:
            # Find all ProductHistory records that reference this batch
            history_records = ProductHistory.query.filter_by(
                reference_id=batch_id,
                reference_type='batch'
            ).all()
            
            # Update the payee field for each record
            for record in history_records:
                # Update the payee to reflect the new supplier name
                record.payee = format_payee_for_transaction(product, supplier_name)
        
        db.session.commit()

        # Log changes
        log_activity(
            action="Update Batch",
            details=(
                f"Updated batch for <strong>{product.name}</strong><br>"
                f"Supplier: <strong>{old_supplier or '-'} ➜ {supplier_name or '-'}</strong><br>"
                f"Expiry: <strong>{old_exp_date.strftime('%Y-%m-%d') if old_exp_date else '-'} ➜ {new_exp_date.strftime('%Y-%m-%d') if new_exp_date else '-'}</strong><br>"
                f"Quantity: <strong>{old_quantity} ➜ {batch.quantity}</strong>"
            )
        )

        return jsonify({'status': 'success', 'message': 'Batch updated successfully'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@products.route('/add_stock', methods=['POST'])
@login_required
@user_redirect_to_requisition
@admin_required
def add_stock():
    product_id = request.form.get('product_id')
    try:
        add_qty = float(request.form.get('quantity', 0))
    except (TypeError, ValueError):
        return jsonify({'message': 'Enter a valid quantity.'}), 400

    if not product_id or add_qty <= 0:
        return jsonify({'message': 'Product and a quantity greater than zero are required.'}), 400

    supplier_name = request.form.get('supplier_name', '').strip() or None

    shelf_life_raw = request.form.get('shelf_life_months', '3').strip()
    is_no_expiry = (shelf_life_raw in ('0', 'no_expiry', 'none', 'no-expiry') or 
                    request.form.get('no_expiry', '').lower() in ('true', '1', 'yes'))

    is_dry_goods = (request.form.get('is_dry_goods', '').lower() in ('true', '1', 'yes') or 
                    bool(request.form.get('direct_exp_date', '').strip()))
    direct_exp_date_str = request.form.get('direct_exp_date', '').strip() or request.form.get('exp_date', '').strip()

    shelf_life_months = None
    if is_no_expiry:
        production_date = None
        exp_date = datetime(2099, 12, 31).date()
        shelf_life_months = 0
    elif is_dry_goods and direct_exp_date_str:
        try:
            exp_date = datetime.strptime(direct_exp_date_str, '%Y-%m-%d').date()
        except (TypeError, ValueError):
            return jsonify({'message': 'Enter a valid expiration date for dry goods.'}), 400
        # For dry goods, production_date is optional
        prod_date_str = request.form.get('production_date', '').strip()
        try:
            production_date = datetime.strptime(prod_date_str, '%Y-%m-%d').date() if prod_date_str else None
        except (TypeError, ValueError):
            production_date = None
    else:
        # Standard perishable goods workflow: production_date + shelf_life_months
        production_date_str = request.form.get('production_date', '').strip()

        try:
            production_date = datetime.strptime(production_date_str, '%Y-%m-%d').date()
        except (TypeError, ValueError):
            # Keep accepting direct exp_date as fallback
            if direct_exp_date_str:
                try:
                    exp_date = datetime.strptime(direct_exp_date_str, '%Y-%m-%d').date()
                    production_date = None
                except (TypeError, ValueError):
                    return jsonify({'message': 'Production date is required.'}), 400
            else:
                return jsonify({'message': 'Production date is required.'}), 400

        if production_date is not None:
            try:
                shelf_life_months = int(shelf_life_raw)
            except (TypeError, ValueError):
                return jsonify({'message': 'Choose a valid shelf life.'}), 400
            if shelf_life_months not in (3, 6, 12):
                return jsonify({'message': 'Shelf life must be 3, 6, or 12 months.'}), 400

            exp_date = add_months_to_date(production_date, shelf_life_months)

    # Get current time in PHT
    current_time = datetime.now(ZoneInfo("Asia/Manila"))

    # Check if product exists and belongs to the user's company
    product_query = Product.query.filter(Product.id == product_id)
    if current_user.role != 'SYS-Admin':
        product_query = product_query.filter(Product.company_id == current_user.company_id)
    product = product_query.first()
    # (company scoping handled above)



    
    if not product:
        return jsonify({'message': 'Product not found'}), 404

    # Create new batch
    try:
        new_batch = WarehouseProductBatch(
            product_id=product_id,
            quantity=add_qty,
            int_quantity=add_qty,
            production_date=production_date,
            exp_date=exp_date,
            supplier_name=supplier_name,

            added_on=current_time,
            sub_barcode=None
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('add_stock failed creating batch')
        return jsonify({'message': f'Could not create batch: {e}'}), 500

    # sub_barcode is now generated above, so we don't need to generate it here
    # new_batch.sub_barcode = generate_sub_barcode(product.barcode, new_batch.exp_date)
    
    db.session.add(new_batch)
    db.session.flush()  # Flush to get the batch ID

    # Now recalculate product warehouse quantity from all batches and sync total
    all_batches = WarehouseProductBatch.query.filter_by(product_id=product_id).all()
    total_batch_quantity = sum(batch.quantity for batch in all_batches)

    product.warehouse_qty = total_batch_quantity
    product.warehouse_initial_qty = max(product.warehouse_initial_qty or 0, total_batch_quantity)
    product.quantity = product.warehouse_qty + product.store_qty
    product.initial_quantity = product.warehouse_initial_qty + (product.store_initial_qty or 0)
    product.last_updated = current_time

    # Create ProductHistory record for TRANS IN (manual addition)
    # Payee should include both product's purchase_order_place and batch's supplier_name when available
    payee = format_payee_for_transaction(product, supplier_name)
    
    history_record = ProductHistory(
        product_id=product_id,
        trxn_date=current_time,
        trxn_code='TRANS IN',
        payee=payee,
        quantity_in=add_qty,
        quantity_out=0.0,
        net_change=add_qty,
        reference_id=new_batch.id,
        reference_type='batch',
        company_id=product.company_id
    )
    db.session.add(history_record)

    db.session.commit()

    # Format the time for logging
    formatted_time = current_time.strftime('%Y-%m-%d %I:%M:%S %p')

    # Determine expiry date for logging
    exp_date_str = exp_date.strftime('%Y-%m-%d')

    if is_no_expiry:
        prod_date_display = 'N/A (No Expiry)'
        shelf_life_display = 'No Expiry'
    else:
        prod_date_display = production_date.strftime('%Y-%m-%d') if production_date else 'N/A (Dry Goods)'
        shelf_life_display = f"{shelf_life_months} months" if shelf_life_months else "N/A (Dry Goods - Direct Expiry)"
    log_activity(
        action="Add Stock",
        details=f"<strong>{add_qty} {product.uom}</strong> added to "
                f"<strong>{product.name}</strong><br>"
                f"Production date: {prod_date_display}<br>"
                f"Shelf life: {shelf_life_display} · Expiry: {exp_date_str}<br>"
                f"Supplier: {supplier_name or 'N/A'}<br>"
                f"Added on: {formatted_time}<br>"
                f"New Total: <span class='badge bg-warning'>{product.quantity} {product.uom}</span>"
    )

    return '', 200


@products.route('/remove_stock', methods=['POST'])
@login_required
@user_redirect_to_requisition
@edit_delete_required
def remove_stock():
    product_id = request.form['product_id']
    batch_id = request.form['batch_id']
    remove_qty = float(request.form['quantity'])
    reason = request.form['reason']
    remarks = request.form.get('remarks', '')

    # Get current time in PHT
    current_time = datetime.now(ZoneInfo("Asia/Manila"))

    # SYS-Admin with no company can remove stock from any company's batches
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
        return "Invalid batch selected", 400

    # SYS-Admin with no company can remove stock from any product
    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        product = Product.query.get(product_id)
    else:
        product = Product.query.filter_by(
            id=product_id,
            company_id=current_user.company_id
        ).first()
    
    if not product:
        return "Product not found", 404

    if batch.quantity < remove_qty:
        return f"Error: Not enough stock in selected batch. Available: {batch.quantity}", 400

    # Update batch quantity
    batch.quantity = batch.quantity - remove_qty

    # Create ProductHistory record for TRANS OUT (manual removal)
    history_record = ProductHistory(
        product_id=product_id,
        trxn_date=current_time,
        trxn_code='TRANS OUT',
        payee=f'Manual Removal - {reason}',
        quantity_in=0.0,
        quantity_out=remove_qty,
        net_change=-remove_qty,
        reference_id=batch.id,
        reference_type='batch'
    )
    # Assign the product's company to the history record.
    # (current_user.company_id is None for SYS-Admin, so use the product's company.)
    history_record.company_id = product.company_id
    db.session.add(history_record)

    # Update product total quantity (warehouse stock)
    product.quantity = product.quantity - remove_qty
    product.warehouse_qty = product.warehouse_qty - remove_qty
    if product.warehouse_qty < 0:
        product.warehouse_qty = 0
    product.last_updated = current_time
    db.session.commit()

    # Format the time for logging
    formatted_time = current_time.strftime('%Y-%m-%d %I:%M:%S %p')

    # Log activity with detailed information
    log_activity(
        action="Remove Stock",
        details=(f"<strong>{remove_qty} {product.uom}</strong> removed from "
                f"<strong>{product.name}</strong><br>"
                f"Batch #{batch.id} (Exp: {batch.exp_date.strftime('%Y-%m-%d')})<br>"
                f"Removed on: {formatted_time}<br>"
                f"Reason: {reason}<br>"
                f"Remarks: {remarks}<br>"
                f"Remaining in batch: {batch.quantity} {product.uom}<br>"
                f"Total remaining: <span class='badge bg-warning'>{product.quantity} {product.uom}</span>")
    )

    return '', 200


@products.route('/lookup_product/<barcode>')
def lookup_product(barcode):
    raw_barcode = str(barcode or '').strip()
    # Hardware scanners may include AIM symbology prefixes or formatting
    # characters, and EAN readers may return a leading zero for a stored
    # 12-digit product code. Try those equivalent representations while
    # keeping the database value unchanged.
    normalized_barcode = raw_barcode
    for prefix in (']C1', ']E0', ']d2', ']Q3'):
        if normalized_barcode.startswith(prefix):
            normalized_barcode = normalized_barcode[len(prefix):]
            break
    normalized_barcode = normalized_barcode.replace(' ', '').replace('-', '')
    barcode_candidates = [raw_barcode, normalized_barcode]
    if normalized_barcode.isdigit():
        if len(normalized_barcode) == 13:
            barcode_candidates.append(normalized_barcode[:12])
            barcode_candidates.append(normalized_barcode[-12:])
        elif len(normalized_barcode) < 12:
            barcode_candidates.append(normalized_barcode.zfill(12))
        barcode_candidates.append(normalized_barcode.lstrip('0'))
    barcode_candidates = list(dict.fromkeys(value for value in barcode_candidates if value))

    # For SYS-Admin users, allow access to all products regardless of company
    if current_user.role == 'SYS-Admin':
        product = Product.query.filter(Product.barcode.in_(barcode_candidates)).first()
    else:
        # For other users, check in their assigned companies
        allowed_comp_ids = current_user.all_company_ids if hasattr(current_user, 'all_company_ids') and current_user.all_company_ids else ([current_user.company_id] if current_user.company_id else [])
        if allowed_comp_ids:
            product = Product.query.filter(
                Product.barcode.in_(barcode_candidates),
                Product.company_id.in_(allowed_comp_ids)
            ).first()
        else:
            product = Product.query.filter(
                Product.barcode.in_(barcode_candidates),
                Product.company_id == current_user.company_id
            ).first()

    if product:
        return jsonify({
            'success': True,
            'id': product.id,
            'name': product.name,
            'quantity': product.quantity,
            'account_title': product.account_title,
            'uom': product.uom,
            'barcode': product.barcode,
            'initial_quantity': product.initial_quantity,
            'low_stock_threshold': product.low_stock_threshold,
            'company_id': product.company_id,
            'reorder_level': product.reorder_level,  # Add reorder_level to the response
            'is_low_stock': product.is_low_stock  # Add is_low_stock property to the response
        })
    else:
        # Check if product exists in another company (for non-SYS-Admin users)
        if current_user.role != 'SYS-Admin':
            product = Product.query.filter(Product.barcode.in_(barcode_candidates)).first()
            if product:
                # Product exists but not in the user's company
                user_company_id = getattr(current_user, 'company_id', None)
                product_company_id = getattr(product, 'company_id', None)
                
                # If user has a company but product doesn't belong to that company, show error
                if user_company_id and product_company_id and user_company_id != product_company_id:
                    try:
                        company_name = product.company.name if product.company else "Unknown Company"
                    except:
                        company_name = "Unknown Company"
                    return jsonify({
                        'success': False, 
                        'message': f'Access denied. This product belongs to {company_name}, not your company.'
                    })
                
                # If user doesn't have a company but product does, show error
                if not user_company_id and product_company_id:
                    try:
                        company_name = product.company.name if product.company else "Unknown Company"
                    except:
                        company_name = "Unknown Company"
                    return jsonify({
                        'success': False, 
                        'message': f'Access denied. This product belongs to {company_name}, not your company.'
                    })
                
                # If product doesn't have a company but user does, show error
                if user_company_id and not product_company_id:
                    return jsonify({
                        'success': False, 
                        'message': 'Access denied. This product does not belong to any company, while you have a company assigned.'
                    })
        
        return jsonify({'success': False, 'message': 'Product not found'})


@products.route('/get_product_batches/<int:product_id>')
@login_required
@admin_required
def get_product_batches(product_id):
    # SYS-Admin users without a company can view batches for any product.
    # Other users are restricted to products in their assigned company.
    if current_user.role == 'SYS-Admin':
        product = Product.query.get_or_404(product_id)
    else:
        product = Product.query.filter_by(
            id=product_id,
            company_id=current_user.company_id
        ).first_or_404()

    # Get all batches ordered by expiration date
    batches = (WarehouseProductBatch.query
               .filter_by(product_id=product_id)
               .order_by(WarehouseProductBatch.exp_date)
               .all())

    # Calculate total quantity
    total_quantity = sum(batch.quantity for batch in batches)

    # Format batch data
    batch_data = []
    current_date = datetime.now(ZoneInfo("Asia/Manila")).date()

    for index, batch in enumerate(batches, start=1):
        # Calculate days until expiry
        days_until_expiry = (batch.exp_date - current_date).days if batch.exp_date else None
        expiry_status = (
            'text-muted' if days_until_expiry is None else
            'text-danger' if days_until_expiry <= 30 else
            'text-warning' if days_until_expiry <= 60 else
            'text-success'
        )

        batch_data.append({
            'id': batch.id,
            'batch_number': index,
            'quantity': batch.quantity,
            'production_date': batch.production_date.strftime('%Y-%m-%d') if batch.production_date else None,
            'exp_date': batch.exp_date.strftime('%Y-%m-%d') if batch.exp_date else None,
            'added_on': batch.added_on.strftime('%Y-%m-%d %I:%M:%S %p') if batch.added_on else None,
            'days_until_expiry': days_until_expiry,
            'expiry_status': expiry_status,
            'percentage': 0,
            'sub_barcode': batch.sub_barcode,

            'supplier_name': batch.supplier_name
        })

    return jsonify({
        'success': True,
        'product_name': product.name,
        'product_uom': product.uom,
        'total_quantity': total_quantity,
        'batches': batch_data
    })


@products.route('/toggle_favorite/<int:product_id>', methods=['POST'])
@login_required
@user_redirect_to_requisition
@admin_required
def toggle_product_favorite(product_id):
    """Toggle favorite status for a product"""
    try:
        # Check if product exists and belongs to the user's company
        product = Product.query.filter_by(
            id=product_id,
            company_id=current_user.company_id
        ).first_or_404()
        
        # Toggle the favorite status
        product.is_favorite = not product.is_favorite
        db.session.commit()
        
        action = "added to" if product.is_favorite else "removed from"
        
        return jsonify({
            'success': True,
            'is_favorite': product.is_favorite,
            'message': f'Product {action} favorites successfully.'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Error toggling favorite: {str(e)}'
        }), 500


@products.route('/export_inventory_xlsx')
@login_required
@user_redirect_to_requisition
def export_inventory_xlsx():
    """Export inventory data as Excel (.xlsx) file."""
    if current_user.role not in ['SYS-Admin', 'WH-Admin', 'Company-Admin', 'Purchaser']:
        flash('Access denied. You do not have permission to export inventory.', 'error')
        return redirect(url_for('products.view_products'))

    try:
        # Get active query filters from request
        search_query = request.args.get('q', '').strip()
        account_type = request.args.get('account_type', '').strip()
        station_filter = request.args.get('station', '').strip()
        status_filter = request.args.get('status', '').strip()
        company_id = request.args.get('company_id', '').strip()
        
        # Base query - filter by current user's company
        if current_user.role == 'SYS-Admin' and current_user.company_id is None:
            # SYS-Admin with no company can see all products
            query = Product.query
        else:
            # Filter by current user's company
            query = Product.query.filter_by(company_id=current_user.company_id)
        
        # Apply company filter for SYS-Admin
        if current_user.role == 'SYS-Admin' and company_id:
            try:
                company_id_int = int(company_id)
                query = query.filter_by(company_id=company_id_int)
            except (ValueError, TypeError):
                pass

        # Apply search filter
        if search_query:
            search_filter = or_(
                Product.name.ilike(f'%{search_query}%'),
                Product.barcode.ilike(f'%{search_query}%'),
                Product.item_uom_desc.ilike(f'%{search_query}%')
            )
            query = query.filter(search_filter)

        # Apply account title filter
        if account_type:
            query = query.filter(Product.account_title == account_type)

        # Apply station filter
        if station_filter:
            query = query.filter(Product.station == station_filter)

        # Apply status filter
        if status_filter:
            if status_filter == 'OK':
                query = query.filter(
                    Product.quantity > 0,
                    db.or_(
                        db.and_(Product.reorder_level > 0, Product.quantity > Product.reorder_level),
                        db.and_(Product.reorder_level == 0, Product.initial_quantity > 0, 
                               Product.quantity > (Product.initial_quantity * (Product.low_stock_threshold / 100)))
                    )
                )
            elif status_filter == 'Low Stock':
                query = query.filter(
                    Product.quantity > 0,
                    db.or_(
                        db.and_(Product.reorder_level > 0, Product.quantity <= Product.reorder_level),
                        db.and_(Product.reorder_level == 0, Product.initial_quantity > 0, 
                               Product.quantity <= (Product.initial_quantity * (Product.low_stock_threshold / 100)))
                    )
                )
            elif status_filter == 'No Stock':
                query = query.filter(Product.quantity == 0)
            elif status_filter == 'Expiring Soon':
                today = datetime.now(ZoneInfo("Asia/Manila")).date()
                thirty_days = today + timedelta(days=30)
                query = query.join(WarehouseProductBatch).filter(
                    WarehouseProductBatch.exp_date.between(today, thirty_days),
                    WarehouseProductBatch.quantity > 0
                ).distinct()
            elif status_filter == 'Expiring 3 Months':
                today = datetime.now(ZoneInfo("Asia/Manila")).date()
                thirty_days = today + timedelta(days=30)
                ninety_days = today + timedelta(days=90)
                query = query.join(WarehouseProductBatch).filter(
                    WarehouseProductBatch.exp_date.between(thirty_days, ninety_days),
                    WarehouseProductBatch.quantity > 0
                ).distinct()
            elif status_filter == 'Expired':
                today = datetime.now(ZoneInfo("Asia/Manila")).date()
                query = query.join(WarehouseProductBatch).filter(
                    WarehouseProductBatch.exp_date < today,
                    WarehouseProductBatch.quantity > 0
                ).distinct()
            elif status_filter == 'Favorites':
                query = query.filter(Product.is_favorite.is_(True))

        # Query all matching products (no restrictive 12 category whitelist)
        products_list = query.order_by(Product.name.asc()).all()

        # Define account codes dictionary for reference
        account_codes = {
            "COS-Beverages": 201, "COS-Ice Cream": 202, "COS-Desserts": 203, "COS-Food": 204,
            "COS-Chicken": 205, "COS-Condiments": 206, "COS-Rice": 207,
            "Supplies-Kitchen": 300, "Supplies-Packaging": 301, "Supplies-Store Dining": 302,
            "Supplies-Store Office": 303, "Supplies-Utility": 304
        }
        
        # Create Excel workbook
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
        
        wb = Workbook()
        ws = wb.active
        ws.title = "Inventory Report"
        ws.views.sheetView[0].showGridLines = True
        
        # Define styles
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
        header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        
        border_color = "CBD5E1"
        thin_border = Border(
            left=Side(style='thin', color=border_color),
            right=Side(style='thin', color=border_color),
            top=Side(style='thin', color=border_color),
            bottom=Side(style='thin', color=border_color)
        )
        
        # Write header row
        headers = [
            'Barcode', 'Product Name', 'Description', 'Station', 'Account Title', 'FS Code',
            'Warehouse Stock', 'Store Stock', 'Total Stock', 'UOM',
            'Stock Status', 'Nearest Expiry Date', 'Purchase Order Place'
        ]
        
        ws.row_dimensions[1].height = 28
        for col_idx, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            cell.border = thin_border
        
        # Write data rows
        now_ph = datetime.now(ZoneInfo("Asia/Manila"))
        current_date = now_ph.date()
        row = 2
        
        # Predefined status styles
        status_styles = {
            "Out of Stock": {
                "fill": PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid"),
                "font": Font(name="Calibri", size=10, bold=True, color="991B1B")
            },
            "Low Stock": {
                "fill": PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid"),
                "font": Font(name="Calibri", size=10, bold=True, color="92400E")
            },
            "In Stock": {
                "fill": PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid"),
                "font": Font(name="Calibri", size=10, bold=True, color="166534")
            }
        }
        expired_fill = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")
        expired_font = Font(name="Calibri", size=10, bold=True, color="991B1B")

        for product in products_list:
            wh_qty = float(product.warehouse_qty or 0.0)
            store_qty = float(product.store_qty or 0.0)
            total_qty = float(product.quantity or 0.0)
            
            # Calculate stock status
            if total_qty == 0:
                stock_status = "Out of Stock"
            elif product.is_low_stock:
                stock_status = "Low Stock"
            else:
                stock_status = "In Stock"
            
            # Get nearest expiry date from warehouse or store batches
            nearest_expiry = "N/A"
            if product.warehouse_batches:
                valid_batches = [b for b in product.warehouse_batches if (b.quantity or 0) > 0 and b.exp_date and b.exp_date.year < 2099]
                if valid_batches:
                    future_batches = [b for b in valid_batches if b.exp_date >= current_date]
                    if future_batches:
                        nearest = min(future_batches, key=lambda x: x.exp_date)
                        nearest_expiry = nearest.exp_date.strftime('%Y-%m-%d')
                    else:
                        nearest_expiry = "EXPIRED"

            if nearest_expiry == "N/A" and product.store_batches:
                valid_store = [b for b in product.store_batches if (b.quantity or 0) > 0 and b.exp_date and b.exp_date.year < 2099]
                if valid_store:
                    future_store = [b for b in valid_store if b.exp_date >= current_date]
                    if future_store:
                        nearest = min(future_store, key=lambda x: x.exp_date)
                        nearest_expiry = nearest.exp_date.strftime('%Y-%m-%d')
                    else:
                        nearest_expiry = "EXPIRED"

            if nearest_expiry == "N/A" and product.exp_date:
                nearest_expiry = str(product.exp_date)
            
            # Row data
            row_data = [
                product.barcode or '',
                product.name or '',
                product.item_uom_desc or '',
                product.station or '-',
                product.account_title or '',
                account_codes.get(product.account_title, ''),
                round(wh_qty, 2),
                round(store_qty, 2),
                round(total_qty, 2),
                product.uom or '',
                stock_status,
                nearest_expiry,
                product.purchase_order_place or ''
            ]
            
            ws.row_dimensions[row].height = 20
            
            for col_idx, value in enumerate(row_data, 1):
                cell = ws.cell(row=row, column=col_idx, value=value)
                cell.font = Font(name="Calibri", size=10)
                cell.border = thin_border
                
                # Alignments & formats
                if col_idx in [1, 4, 6, 10, 11, 12]:  # Barcode, Station, FS Code, UOM, Status, Expiry
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                elif col_idx in [7, 8, 9]:  # Numbers
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                    cell.number_format = '#,##0.00'
                else:
                    cell.alignment = Alignment(horizontal="left", vertical="center")
                
                # Highlight Stock Status
                if col_idx == 11 and value in status_styles:
                    cell.fill = status_styles[value]["fill"]
                    cell.font = status_styles[value]["font"]

                # Highlight Expired
                if col_idx == 12 and value == "EXPIRED":
                    cell.fill = expired_fill
                    cell.font = expired_font
            
            row += 1
        
        # Enable Excel Auto-Filter and freeze header row
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max(row - 1, 1)}"
        
        # Auto-adjust column widths cleanly
        for column in ws.columns:
            max_len = 0
            col_letter = get_column_letter(column[0].column)
            for cell in column:
                val = cell.value
                if val is not None:
                    max_len = max(max_len, len(str(val)))
            ws.column_dimensions[col_letter].width = max(max_len + 3, 12)
        
        # Save workbook to buffer
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        
        timestamp = now_ph.strftime('%Y%m%d_%H%M%S')
        filename = f"inventory_export_{timestamp}.xlsx"
        
        return Response(
            output.getvalue(),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Access-Control-Expose-Headers": "Content-Disposition"
            }
        )
        
    except Exception as e:
        log_activity(
            action="Export Excel Error",
            details=f"Failed to export Excel: {str(e)}"
        )
        if request.headers.get('Accept') == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' or request.is_json:
            return jsonify({'status': 'error', 'message': f'Failed to export Excel: {str(e)}'}), 500
        flash(f'Error exporting Excel: {str(e)}', 'error')
        return redirect(url_for('products.view_products'))



@products.route('/import_products_csv', methods=['GET', 'POST'])
@login_required
@user_redirect_to_requisition
@admin_required
def import_products_csv():
    """Import products from CSV file"""
    if request.method == 'GET':
        return render_template('shared/import_products.html')
    
    if 'csv_file' not in request.files:
        flash('No file selected', 'error')
        return redirect(request.url)
    
    file = request.files['csv_file']
    if file.filename == '':
        flash('No file selected', 'error')
        return redirect(request.url)
    
    if not (file.filename.endswith('.csv') or file.filename.endswith('.xlsx')):
        flash('Please upload a CSV or Excel (.xlsx) file', 'error')
        return redirect(request.url)
    
    try:
        # Read file content based on file type
        if file.filename.endswith('.csv'):
            # Handle CSV file
            csv_content = file.read().decode('utf-8')
            csv_reader = csv.DictReader(io.StringIO(csv_content))
        elif file.filename.endswith('.xlsx'):
            # Handle Excel file
            file.seek(0)  # Reset file pointer
            workbook = load_workbook(file, data_only=True)
            sheet = workbook.active
            
            # Get headers from first row
            headers = [cell.value for cell in sheet[1] if cell.value]
            
            # Create reader-like object for Excel
            class ExcelReader:
                def __init__(self, sheet, headers):
                    self.sheet = sheet
                    self.headers = headers
                    self.current_row = 2  # Start from second row (after headers)
                
                def __iter__(self):
                    return self
                
                def __next__(self):
                    if self.current_row > self.sheet.max_row:
                        raise StopIteration
                    
                    row_data = {}
                    for col, header in enumerate(self.headers, 1):
                        cell_value = self.sheet.cell(row=self.current_row, column=col).value
                        row_data[header] = str(cell_value) if cell_value is not None else ''
                    
                    self.current_row += 1
                    return row_data
            
            csv_reader = ExcelReader(sheet, headers)
        
        imported_count = 0
        skipped_count = 0
        errors = []
        
        for row_num, row in enumerate(csv_reader, start=2):  # Start from 2 because row 1 is header
            try:
                # Validate required fields
                required_fields = ['name', 'account_title', 'uom']
                for field in required_fields:
                    if not row.get(field) or row[field].strip() == '':
                        errors.append(f"Row {row_num}: Missing required field '{field}'")
                        continue
                
                # Check if product already exists (by name and account_title)
                existing_product = Product.query.filter_by(
                    name=row['name'].strip(),
                    account_title=row['account_title'].strip()
                ).first()
                
                if existing_product:
                    errors.append(f"Row {row_num}: Product '{row['name']}' already exists")
                    skipped_count += 1
                    continue
                
                # Generate unique barcode
                barcode = generate_barcode()
                
                # Parse quantity (optional, defaults to 0)
                quantity = 0.0  # default to 0 if not provided
                if row.get('quantity') and row['quantity'].strip():
                    try:
                        quantity = float(row['quantity'])
                        if quantity < 0:
                            errors.append(f"Row {row_num}: Quantity must be non-negative")
                            continue
                    except ValueError:
                        errors.append(f"Row {row_num}: Invalid quantity format")
                        continue
                
                # Parse low stock threshold
                low_stock_threshold = 10  # default
                if row.get('low_stock_threshold'):
                    try:
                        low_stock_threshold = int(row['low_stock_threshold'])
                        if low_stock_threshold < 0 or low_stock_threshold > 100:
                            errors.append(f"Row {row_num}: Low stock threshold must be between 0-100")
                            continue
                    except ValueError:
                        errors.append(f"Row {row_num}: Invalid low stock threshold format")
                        continue
                    
                # Parse reorder level (optional, defaults to 0)
                reorder_level = 0  # default
                if row.get('reorder_level'):
                    try:
                        reorder_level = int(row['reorder_level'])
                        if reorder_level < 0:
                            errors.append(f"Row {row_num}: Reorder level must be non-negative")
                            continue
                    except ValueError:
                        errors.append(f"Row {row_num}: Invalid reorder level format")
                        continue
                
                # Parse expiration date
                exp_date = None
                if row.get('exp_date') and row['exp_date'].strip():
                    try:
                        exp_date = datetime.strptime(row['exp_date'].strip(), '%Y-%m-%d').date()
                    except ValueError:
                        errors.append(f"Row {row_num}: Invalid date format. Use YYYY-MM-DD")
                        continue
                
                # For supplies categories, if no expiry given, treat as non-expiring
                supplies_categories = ['Supplies-Kitchen', 'Supplies-Packaging', 'Supplies-Store Dining', 'Supplies-Store Office', 'Supplies-Utility']
                if not exp_date and (row['account_title'] in supplies_categories or row['account_title'].lower().startswith('supplies')):
                    exp_date = datetime(2099, 12, 31).date()
                
                # Create new product
                new_product = Product(
                    barcode=barcode,
                    name=row['name'].strip(),
                    quantity=quantity,
                    initial_quantity=quantity,
                    warehouse_qty=quantity,
                    warehouse_initial_qty=quantity,
                    store_qty=0,
                    store_initial_qty=0,
                    low_stock_threshold=low_stock_threshold,
                    reorder_level=reorder_level,  # Add reorder level to product
                    account_title=row['account_title'].strip(),
                    item_uom_desc=row.get('item_uom_desc', '').strip(),
                    uom_conversion=row.get('uom_conversion', '1'),
                    uom=row['uom'].strip(),
                    purchase_order_place=row.get('purchase_order_place', '').strip(),
                    exp_date=row.get('exp_date', '')
                )
                
                # Assign to current user's company
                new_product = assign_company(new_product)
                ensure_product_barcode(new_product)
                
                db.session.add(new_product)
                db.session.flush()  # so we can use new_product.id
                
                # Create batch if expiration date is provided AND there's stock
                if exp_date and quantity > 0:
                    first_batch = WarehouseProductBatch(
                        product_id=new_product.id,
                        quantity=quantity,
                        int_quantity=quantity,
                        exp_date=exp_date,
                        supplier_name=row.get('supplier_name', '').strip(),
                        sub_barcode=None
                    )
                    db.session.add(first_batch)
                
                imported_count += 1
                
            except Exception as e:
                errors.append(f"Row {row_num}: {str(e)}")
                # Rollback the session to clear any failed transaction
                db.session.rollback()
                continue
        
        # Commit all successful imports
        if imported_count > 0:
            db.session.commit()
            
            log_activity(
                action="Import Products from CSV",
                details=f"Successfully imported <strong>{imported_count}</strong> products from CSV file. "
                        f"Skipped: {skipped_count} products."
            )
            
            flash(f'Successfully imported {imported_count} products. Skipped {skipped_count} products.', 'success')
        else:
            db.session.rollback()
            flash('No products were imported. Please check the CSV format and data.', 'error')
        
        # Show errors if any
        if errors:
            error_message = f"Import completed with {len(errors)} errors:\n" + "\n".join(errors[:10])  # Show first 10 errors
            if len(errors) > 10:
                error_message += f"\n... and {len(errors) - 10} more errors"
            flash(error_message, 'warning')
        
        return redirect(url_for('products.view_products'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error importing CSV: {str(e)}', 'error')
        # Log the full error for debugging
        import traceback
        print(f"Import error: {traceback.format_exc()}")
        return redirect(request.url)


@products.route('/import_from_product_dict', methods=['POST'])
@login_required
@user_redirect_to_requisition
@admin_required
def import_from_product_dict():
    """Import products from the product_dict.csv file in the root directory"""
    csv_file_path = os.path.join(current_app.root_path, 'product_dict.csv')
    
    if not os.path.exists(csv_file_path):
        flash('product_dict.csv file not found in the application root directory', 'error')
        return redirect(url_for('products.view_products'))
    
    try:
        with open(csv_file_path, 'r', encoding='utf-8') as file:
            csv_reader = csv.DictReader(file)
            
            imported_count = 0
            skipped_count = 0
            errors = []
            
            for row_num, row in enumerate(csv_reader, start=2):  # Start from 2 because row 1 is header
                try:
                    # Validate required fields
                    required_fields = ['name', 'account_title', 'uom']
                    for field in required_fields:
                        if not row.get(field) or row[field].strip() == '':
                            errors.append(f"Row {row_num}: Missing required field '{field}'")
                            continue
                    
                    # Check if product already exists (by name and account_title)
                    existing_product = Product.query.filter_by(
                        name=row['name'].strip(),
                        account_title=row['account_title'].strip()
                    ).first()
                    
                    if existing_product:
                        errors.append(f"Row {row_num}: Product '{row['name']}' already exists")
                        skipped_count += 1
                        continue
                    
                    # Generate unique barcode
                    barcode = generate_barcode()
                    
                    # Parse quantity (optional, defaults to 0)
                    quantity = 0.0  # default to 0 if not provided
                    if row.get('quantity') and row['quantity'].strip():
                        try:
                            quantity = float(row['quantity'])
                            if quantity < 0:
                                errors.append(f"Row {row_num}: Quantity must be non-negative")
                                continue
                        except ValueError:
                            errors.append(f"Row {row_num}: Invalid quantity format")
                            continue
                    
                    # Parse low stock threshold
                    low_stock_threshold = 10  # default
                    if row.get('low_stock_threshold'):
                        try:
                            low_stock_threshold = int(row['low_stock_threshold'])
                            if low_stock_threshold < 0 or low_stock_threshold > 100:
                                errors.append(f"Row {row_num}: Low stock threshold must be between 0-100")
                                continue
                        except ValueError:
                            errors.append(f"Row {row_num}: Invalid low stock threshold format")
                            continue
                    
                    # Parse expiration date
                    exp_date = None
                    if row.get('exp_date') and row['exp_date'].strip():
                        try:
                            exp_date = datetime.strptime(row['exp_date'].strip(), '%Y-%m-%d').date()
                        except ValueError:
                            errors.append(f"Row {row_num}: Invalid date format. Use YYYY-MM-DD")
                            continue
                    
                    # For supplies categories, if no expiry given, treat as non-expiring
                    supplies_categories = ['Supplies-Kitchen', 'Supplies-Packaging', 'Supplies-Store Dining', 'Supplies-Store Office', 'Supplies-Utility']
                    if not exp_date and (row['account_title'] in supplies_categories or row['account_title'].lower().startswith('supplies')):
                        exp_date = datetime(2099, 12, 31).date()
                    
                    # Create new product
                    new_product = Product(
                        barcode=barcode,
                        name=row['name'].strip(),
                        quantity=quantity,
                        initial_quantity=quantity,
                        low_stock_threshold=low_stock_threshold,
                        account_title=row['account_title'].strip(),
                        item_uom_desc=row.get('item_uom_desc', '').strip(),
                        uom_conversion=row.get('uom_conversion', '1'),
                        uom=row['uom'].strip(),
                        purchase_order_place=row.get('purchase_order_place', '').strip(),
                        exp_date=row.get('exp_date', '')
                    )
                    
                    # Assign to current user's company
                    new_product = assign_company(new_product)
                    ensure_product_barcode(new_product)
                    
                    db.session.add(new_product)
                    db.session.flush()  # so we can use new_product.id
                    
                    # Create batch if expiration date is provided AND there's stock
                    if exp_date and quantity > 0:
                        first_batch = WarehouseProductBatch(
                            product_id=new_product.id,
                            quantity=quantity,
                            int_quantity=quantity,
                            exp_date=exp_date,
                            supplier_name=row.get('supplier_name', '').strip(),
                            sub_barcode=None
                        )
                        db.session.add(first_batch)
                    
                    imported_count += 1
                    
                except Exception as e:
                    errors.append(f"Row {row_num}: {str(e)}")
                    # Rollback the session to clear any failed transaction
                    db.session.rollback()
                    continue
            
            # Commit all successful imports
            if imported_count > 0:
                db.session.commit()
                
                log_activity(
                    action="Import Products from product_dict.csv",
                    details=f"Successfully imported <strong>{imported_count}</strong> products from product_dict.csv. "
                            f"Skipped: {skipped_count} products."
                )
                
                flash(f'Successfully imported {imported_count} products from product_dict.csv. Skipped {skipped_count} products.', 'success')
            else:
                db.session.rollback()
                flash('No products were imported. Please check the CSV format and data.', 'error')
            
            # Show errors if any
            if errors:
                error_message = f"Import completed with {len(errors)} errors:\n" + "\n".join(errors[:10])  # Show first 10 errors
                if len(errors) > 10:
                    error_message += f"\n... and {len(errors) - 10} more errors"
                flash(error_message, 'warning')
            
            return redirect(url_for('products.view_products'))
            
    except Exception as e:
        db.session.rollback()
        flash(f'Error importing from product_dict.csv: {str(e)}', 'error')
        return redirect(url_for('products.view_products'))


@products.route('/product_history/<int:product_id>')
@login_required
@user_redirect_to_requisition
def product_history(product_id):
    """Display transaction history for a specific product"""
    # Check if product exists and belongs to the user's company
    if current_user.role == 'SYS-Admin':
        # SYS-Admin can access any product
        product = Product.query.get_or_404(product_id)
    else:
        # Other users must belong to the same company
        product = Product.query.filter_by(
            id=product_id,
            company_id=current_user.company_id
        ).first_or_404()
    
    # A direct URL is routed back to Products, where history opens in-place as a modal.
    if request.args.get('modal') != '1':
        return redirect(url_for('products.view_products', history_id=product_id))

    page = max(request.args.get('page', 1, type=int), 1)
    page_size = 30
    history_query = ProductHistory.query.filter_by(product_id=product_id)
    history_count = history_query.count()
    history_records = history_query.order_by(
        ProductHistory.trxn_date.desc(), ProductHistory.id.desc()
    ).offset((page - 1) * page_size).limit(page_size).all()
    has_more = page * page_size < history_count

    if request.args.get('rows') == '1':
        response = current_app.make_response(render_template(
            'shared/product_history_rows.html',
            product=product,
            history_records=history_records,
        ))
        response.headers['X-History-Has-More'] = str(has_more).lower()
        response.headers['X-History-Next-Page'] = str(page + 1)
        response.headers['X-History-Total'] = str(history_count)
        return response

    return render_template(
        'shared/product_history_modal.html',
        product=product,
        history_records=history_records,
        history_count=history_count,
        history_has_more=has_more,
    )


# ─────────────────────────────────────────────────
#  REQUEST DELETION — WH-Admin requests to delete a transaction
# ─────────────────────────────────────────────────
@products.route('/request_deletion/<int:history_id>', methods=['POST'])
@login_required
def request_deletion(history_id):
    """WH-Admin requests deletion of a ProductHistory record. Requires Company-Admin approval."""
    from models import Notification
    record = ProductHistory.query.get_or_404(history_id)

    # Only WH-Admin and SYS-Admin can request deletion
    if current_user.role not in ('WH-Admin', 'SYS-Admin'):
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    # Must belong to same company (or SYS-Admin)
    if current_user.role != 'SYS-Admin' and record.company_id != current_user.company_id:
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    # Check for existing pending request on same record
    existing = DeletionRequest.query.filter_by(
        product_history_id=history_id, status='Pending'
    ).first()
    if existing:
        return jsonify({'success': False, 'message': 'A deletion request for this transaction is already pending.'}), 400

    data = request.get_json(silent=True) or {}
    reason = (data.get('reason') or '').strip()
    if not reason:
        return jsonify({'success': False, 'message': 'Please provide a reason for deletion.'}), 400

    dr = DeletionRequest(
        product_history_id=history_id,
        product_id=record.product_id,
        trxn_code=record.trxn_code,
        quantity_in=record.quantity_in,
        quantity_out=record.quantity_out,
        net_change=record.net_change,
        reason=reason,
        requested_by=current_user.id,
        company_id=record.company_id,
    )
    db.session.add(dr)

    # Notify Company-Admin(s) of this company
    admins = User.query.filter_by(role='Company-Admin', company_id=record.company_id).all()
    product = Product.query.get(record.product_id)
    prod_name = product.name if product else 'Unknown'
    for admin in admins:
        notif = Notification(
            user_id=admin.id,
            title='Deletion Request Pending',
            message=f'{current_user.full_name} requested deletion of a {record.trxn_code} transaction for "{prod_name}". Reason: {reason}',
            type='warning',
            reference_type='deletion_request',
            reference_id=dr.id,
        )
        db.session.add(notif)

    log_activity(
        action='Deletion request submitted',
        details=f'{current_user.full_name} requested deletion of {record.trxn_code} (id={history_id}) for "{prod_name}". Reason: {reason}',
    )

    try:
        db.session.commit()
        return jsonify({'success': True, 'message': 'Deletion request submitted. Awaiting Company-Admin approval.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'}), 500


# ─────────────────────────────────────────────────
#  DELETION REQUESTS — Company-Admin manages pending requests
# ─────────────────────────────────────────────────
@products.route('/deletion_requests')
@login_required
def deletion_requests_page():
    """Company-Admin page to view and manage deletion requests."""
    if current_user.role not in ('Company-Admin', 'SYS-Admin'):
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))
    return render_template('shared/deletion_requests.html')


@products.route('/api/deletion_requests')
@login_required
def api_deletion_requests():
    """API: list deletion requests scoped by role."""
    if current_user.role not in ('Company-Admin', 'SYS-Admin'):
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    status_filter = request.args.get('status', 'all')

    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        query = DeletionRequest.query
    else:
        query = DeletionRequest.query.filter_by(company_id=current_user.company_id)

    if status_filter != 'all':
        query = query.filter_by(status=status_filter)

    requests = query.order_by(DeletionRequest.requested_at.desc()).all()

    rows = []
    for dr in requests:
        product = Product.query.get(dr.product_id)
        requester = User.query.get(dr.requested_by)
        reviewer = User.query.get(dr.reviewed_by) if dr.reviewed_by else None
        rows.append({
            'id': dr.id,
            'product_name': product.name if product else 'Deleted',
            'trxn_code': dr.trxn_code,
            'quantity_in': dr.quantity_in,
            'quantity_out': dr.quantity_out,
            'net_change': dr.net_change,
            'reason': dr.reason,
            'status': dr.status,
            'requested_by': requester.full_name if requester else 'Unknown',
            'requested_at': dr.requested_at.strftime('%Y-%m-%d %I:%M %p') if dr.requested_at else '',
            'reviewed_by': reviewer.full_name if reviewer else None,
            'reviewed_at': dr.reviewed_at.strftime('%Y-%m-%d %I:%M %p') if dr.reviewed_at else None,
            'review_remarks': dr.review_remarks,
        })

    return jsonify({'success': True, 'rows': rows})


@products.route('/api/deletion_requests/<int:dr_id>/approve', methods=['POST'])
@login_required
def approve_deletion_request(dr_id):
    """Company-Admin approves a deletion request — actually deletes the transaction and reverses stock."""
    from models import Notification
    dr = DeletionRequest.query.get_or_404(dr_id)

    if current_user.role not in ('Company-Admin', 'SYS-Admin'):
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    if current_user.role == 'Company-Admin' and dr.company_id != current_user.company_id:
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    if dr.status != 'Pending':
        return jsonify({'success': False, 'message': 'This request has already been reviewed.'}), 400

    data = request.get_json(silent=True) or {}
    remarks = (data.get('remarks') or '').strip()

    # 1. Reverse stock changes on the product
    record = ProductHistory.query.get(dr.product_history_id) if dr.product_history_id else None
    if record:
        product = Product.query.get(dr.product_id)
        if product:
            # Reverse stock changes on warehouse_qty, store_qty, and total quantity
            if record.reference_type == 'batch':
                product.warehouse_qty -= record.net_change
                if product.warehouse_qty < 0:
                    product.warehouse_qty = 0
            elif record.reference_type == 'requisition':
                # Reversing a requisition transfer: return to warehouse, deduct from store
                product.warehouse_qty += record.quantity_out
                product.store_qty -= record.quantity_out
                if product.store_qty < 0:
                    product.store_qty = 0
            product.quantity = product.warehouse_qty + product.store_qty

            # Also reverse batch-level changes if possible
            if record.reference_type == 'batch' and record.reference_id:
                batch = WarehouseProductBatch.query.get(record.reference_id)
                if batch:
                    if record.trxn_code == 'TRANS IN':
                        batch.quantity -= record.quantity_in
                        if batch.quantity < 0:
                            batch.quantity = 0
                    elif record.trxn_code == 'TRANS OUT':
                        batch.quantity += record.quantity_out

        # 2. Clear the backref relationship so deletion doesn't cascade
        dr.product_history_id = None
        db.session.flush()  # flush before deleting

        # 3. Delete the ProductHistory record
        db.session.delete(record)

    # 3. Update DeletionRequest status
    dr.status = 'Approved'
    dr.reviewed_by = current_user.id
    dr.reviewed_at = datetime.now(ZoneInfo('Asia/Manila'))
    dr.review_remarks = remarks or 'Approved'

    # 4. Notify the requester
    notif = Notification(
        user_id=dr.requested_by,
        title='Deletion Request Approved',
        message=f'Your deletion request for {dr.trxn_code} (Product #{dr.product_id}) has been approved by {current_user.full_name}.{" " + remarks if remarks else ""}',
        type='success',
        reference_type='deletion_request',
        reference_id=dr.id,
    )
    db.session.add(notif)

    log_activity(
        action='Deletion request approved',
        details=f'{current_user.full_name} approved deletion of {dr.trxn_code} for Product #{dr.product_id}. {remarks or ""}',
    )

    try:
        db.session.commit()
        return jsonify({'success': True, 'message': 'Transaction deleted and stock reversed.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'}), 500


@products.route('/api/deletion_requests/<int:dr_id>/reject', methods=['POST'])
@login_required
def reject_deletion_request(dr_id):
    """Company-Admin rejects a deletion request."""
    from models import Notification
    dr = DeletionRequest.query.get_or_404(dr_id)

    if current_user.role not in ('Company-Admin', 'SYS-Admin'):
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    if current_user.role == 'Company-Admin' and dr.company_id != current_user.company_id:
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    if dr.status != 'Pending':
        return jsonify({'success': False, 'message': 'This request has already been reviewed.'}), 400

    data = request.get_json(silent=True) or {}
    remarks = (data.get('remarks') or '').strip()

    dr.status = 'Rejected'
    dr.reviewed_by = current_user.id
    dr.reviewed_at = datetime.now(ZoneInfo('Asia/Manila'))
    dr.review_remarks = remarks or 'Rejected'

    # Notify the requester
    notif = Notification(
        user_id=dr.requested_by,
        title='Deletion Request Rejected',
        message=f'Your deletion request for {dr.trxn_code} (Product #{dr.product_id}) has been rejected by {current_user.full_name}.{" " + remarks if remarks else ""}',
        type='danger',
        reference_type='deletion_request',
        reference_id=dr.id,
    )
    db.session.add(notif)

    log_activity(
        action='Deletion request rejected',
        details=f'{current_user.full_name} rejected deletion of {dr.trxn_code} for Product #{dr.product_id}. {remarks or ""}',
    )

    try:
        db.session.commit()
        return jsonify({'success': True, 'message': 'Deletion request rejected.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'}), 500


@products.route('/delete_product/<int:product_id>', methods=['POST'])
@login_required
@edit_delete_required
def delete_product(product_id):
    """Delete a product and all its batches, history, and related records"""
    try:
        # Check if product exists and belongs to the user's company
        # For SYS-Admin users, allow deletion of any product regardless of company_id
        if current_user.role == 'SYS-Admin' and current_user.company_id is None:
            # SYS-Admin can delete any product
            product = Product.query.get(product_id)
        else:
            # Regular users can only delete products in their company
            product = Product.query.filter_by(
                id=product_id,
                company_id=current_user.company_id
            ).first()
        
        if not product:
            flash('Product not found or access denied', 'error')
            return redirect(url_for('products.view_products'))
        
        # Get all related records before deleting the product
        # Check if product has any pending removals (approved, rejected, or pending)
        pending_removals = PendingRemoval.query.filter_by(product_id=product_id).all()
        
        # Get all batches for this product
        batches = WarehouseProductBatch.query.filter_by(product_id=product_id).all()
        
        # Get all history records for this product
        history_records = ProductHistory.query.filter_by(product_id=product_id).all()
        
        # Get all requisition items for this product
        requisition_items = RequisitionItem.query.filter_by(product_id=product_id).all()
        
        # Get all stock audits for this product
        stock_audits = StockAudit.query.filter_by(product_id=product_id).all()
        
        # Start deleting related records
        # Delete all pending removals
        for removal in pending_removals:
            db.session.delete(removal)
        
        # Delete all stock audits
        for audit in stock_audits:
            db.session.delete(audit)
        
        # Delete all batches
        for batch in batches:
            db.session.delete(batch)
        
        # Delete all history records
        for history in history_records:
            db.session.delete(history)
        
        # Delete all requisition items
        for item in requisition_items:
            db.session.delete(item)
        
        # Log the deletion
        log_activity(
            action="Delete Product",
            details=f"Deleted product <strong>{product.name}</strong> (Barcode: {product.barcode}) "
                    f"with {len(batches)} batches, {len(history_records)} history records, "
                    f"{len(requisition_items)} requisition items, {len(stock_audits)} stock audits, "
                    f"and {len(pending_removals)} pending removals"
        )
        
        # Delete the product itself
        db.session.delete(product)
        db.session.commit()
        
        flash(f'Product "{product.name}" deleted successfully', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting product: {str(e)}', 'error')
    
    # Preserve search parameters when redirecting
    # Get the referrer URL to maintain search parameters
    referrer = request.referrer
    if referrer and '/products/products' in referrer:
        # If coming from the products page, redirect back to it with parameters
        return redirect(referrer)
    else:
        # Fallback to default products view
        return redirect(url_for('products.view_products'))
