# Standard library imports
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Third-party imports
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from flask_mail import Message
from models import User

# Local imports
from extensions import db
from models import Product, Requisition, ActivityLog, WarehouseProductBatch, StoreProductBatch
from helpers import user_redirect_to_requisition, admin_required, log_activity, calculate_stock_forecast

# Create blueprint
main = Blueprint('main', __name__)


@main.route('/store_inventory')
@login_required
def store_inventory():
    return redirect(url_for('requisitions.store_inventory', **request.args))


@main.route('/')
@login_required
@user_redirect_to_requisition
def dashboard():
    """Display the main dashboard with key metrics and recent activity"""
    # Get current time in Philippines timezone
    now_ph = datetime.now(ZoneInfo("Asia/Manila"))
    today = now_ph.date()
    
    # Get the expiry view parameter (default to '30days')
    expiry_view = request.args.get('expiry_view', '30days')
    
    # Base queries based on user role
    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        # SYS-Admin with no company can see all data
        product_query = Product.query
        requisition_query = Requisition.query
        activity_log_query = ActivityLog.query
    else:
        # Company-Admin and other admins can only see data from their company
        product_query = Product.query.filter_by(company_id=current_user.company_id)
        requisition_query = Requisition.query.filter_by(company_id=current_user.company_id)
        activity_log_query = ActivityLog.query.filter_by(company_id=current_user.company_id)
    
    total_inventory = product_query.count()
    total_requisitions = requisition_query.count()
    pending_requisitions = requisition_query.filter_by(status='Pending').count()
    
    # Calculate low stock count using raw SQL logic instead of the property
    low_stock_count = product_query.filter(
        Product.quantity > 0,  # Exclude out-of-stock items from low stock count
        db.or_(
            db.and_(Product.reorder_level > 0, Product.quantity <= Product.reorder_level),
            db.and_(Product.reorder_level == 0, Product.initial_quantity > 0, 
                   Product.quantity <= (Product.initial_quantity * (Product.low_stock_threshold / 100)))
        )
    ).count()

    # Calculate out of stock count
    out_of_stock_count = product_query.filter_by(quantity=0).count()

    # Get low stock products (for the table) using raw SQL logic
    low_stock_items = product_query.filter(
        Product.quantity > 0,  # Exclude out-of-stock from this list too
        db.or_(
            db.and_(Product.reorder_level > 0, Product.quantity <= Product.reorder_level),
            db.and_(Product.reorder_level == 0, Product.initial_quantity > 0, 
                   Product.quantity <= (Product.initial_quantity * (Product.low_stock_threshold / 100)))
        )
    ).order_by(Product.name).limit(5).all()

    # Calculate expiring products count based on view
    if expiry_view == '3months':
        # For 3 months view, show products expiring within 90 days
        expiry_date = today + timedelta(days=90)
    else:
        # For 30 days view, show products expiring within 30 days
        expiry_date = today + timedelta(days=30)
        
    expiring_30d_count = product_query.join(WarehouseProductBatch).filter(
        WarehouseProductBatch.exp_date.between(today, expiry_date),
        WarehouseProductBatch.quantity > 0
    ).distinct().count()

    # Recent activity logs
    recent_logs = activity_log_query.order_by(ActivityLog.timestamp.desc()).limit(5).all()

    # Get top 5 favorite products ordered by stock status (out of stock first, then low stock, then in stock)
    # First, get all favorite products
    all_favorite_products = product_query.filter(Product.is_favorite == True).all()
    
    # Sort them manually by stock status priority
    out_of_stock = []
    low_stock = []
    in_stock = []
    
    for product in all_favorite_products:
        if product.quantity == 0:
            out_of_stock.append(product)
        else:
            # Use the same logic as in the is_low_stock property
            is_low = False
            if product.reorder_level > 0:
                is_low = product.quantity <= product.reorder_level
            elif product.initial_quantity > 0:
                threshold_qty = product.initial_quantity * (product.low_stock_threshold / 100)
                is_low = product.quantity <= threshold_qty
            
            if is_low:
                low_stock.append(product)
            else:
                in_stock.append(product)
    
    # Combine the lists in priority order and limit to 5
    favorite_products = out_of_stock + low_stock + in_stock
    favorite_products = favorite_products[:5]

    # Get products expiring based on the selected view
    expiring_products = product_query.join(WarehouseProductBatch).filter(
        WarehouseProductBatch.exp_date.between(today, expiry_date),
        WarehouseProductBatch.quantity > 0
    ).distinct().order_by(WarehouseProductBatch.exp_date).limit(5).all()

    # Get expired products for dashboard display (top 5)
    expired_products_top5 = []
    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        # SYS-Admin with no company can see all data
        expired_query = Product.query
    else:
        # Company-Admin and other admins can only see data from their company
        expired_query = Product.query.filter_by(company_id=current_user.company_id)
    
    # Get all products with expired batches
    all_expired_products = expired_query.join(WarehouseProductBatch).filter(
        WarehouseProductBatch.exp_date <= today,
        WarehouseProductBatch.quantity > 0
    ).distinct().all()
    
    # Process expired products to get the necessary data
    for product in all_expired_products:
        expired_batches = [batch for batch in product.warehouse_batches if batch.exp_date <= today and batch.quantity > 0]
        if expired_batches:
            # Sort batches by expiration date (oldest first)
            expired_batches.sort(key=lambda x: x.exp_date)
            earliest_expired_batch = expired_batches[0]
            days_overdue = (today - earliest_expired_batch.exp_date).days
            
            expired_products_top5.append({
                'product': product,
                'earliest_expired_batch': earliest_expired_batch,
                'expired_batches': expired_batches,
                'days_overdue': days_overdue,
                'total_expired_qty': sum(batch.quantity for batch in expired_batches)
            })
    
    # Sort by days overdue (most overdue first) and limit to 5
    expired_products_top5.sort(key=lambda x: x['days_overdue'], reverse=True)
    expired_products_top5 = expired_products_top5[:5]

    # Generate data for top products donut chart
    # Get top 5 products by quantity
    top_products = product_query.order_by(Product.quantity.desc()).limit(5).all()
    top_product_labels = [product.name for product in top_products]
    top_product_quantities = [product.quantity for product in top_products]

    # Generate default data for area chart (month view)
    now = datetime.now(ZoneInfo("Asia/Manila"))
    start_date = now - timedelta(days=30)
    
    # Get stock movements within the date range
    movements = ActivityLog.query.filter(
        ActivityLog.timestamp >= start_date,
        ActivityLog.action.in_(['Add Stock', 'Remove Stock'])
    ).order_by(ActivityLog.timestamp).all()
    
    # Group movements by date
    daily_data = {}
    current_date = start_date.date()
    
    while current_date <= now.date():
        daily_data[current_date] = {'added': 0, 'removed': 0}
        current_date += timedelta(days=1)
    
    # Process movements
    for movement in movements:
        move_date = movement.timestamp.date()
        if move_date in daily_data:
            if 'Add Stock' in movement.action:
                # Extract quantity from movement details
                try:
                    # Look for quantity in the details (e.g., "Added 50 units")
                    import re
                    quantity_match = re.search(r'(\d+(?:\.\d+)?)', movement.details)
                    if quantity_match:
                        quantity = float(quantity_match.group(1))
                        daily_data[move_date]['added'] += quantity
                    else:
                        daily_data[move_date]['added'] += 1  # Fallback to count if no quantity found
                except:
                    daily_data[move_date]['added'] += 1  # Fallback to count
            elif 'Remove Stock' in movement.action:
                # Extract quantity from movement details
                try:
                    # Look for quantity in the details (e.g., "Removed 25 units")
                    import re
                    quantity_match = re.search(r'(\d+(?:\.\d+)?)', movement.details)
                    if quantity_match:
                        quantity = float(quantity_match.group(1))
                        daily_data[move_date]['removed'] += quantity
                    else:
                        daily_data[move_date]['removed'] += 1  # Fallback to count if no quantity found
                except:
                    daily_data[move_date]['removed'] += 1  # Fallback to count
    
    # Prepare chart data
    labels = []
    added_data = []
    removed_data = []
    
    for date, data in daily_data.items():
        labels.append(date.strftime('%b %d'))
        added_data.append(data['added'])
        removed_data.append(data['removed'])

    # Generate dynamic stock status message
    stock_status = "All stock levels are looking good today" # Default message

    # Update stock status based on actual counts
    if low_stock_count > 0:
        stock_status = f"You have <span class='highlight warning'>{low_stock_count} item(s)</span> below stock threshold."
    if out_of_stock_count > 0:
        if stock_status == "All stock levels are looking good today": # If only out of stock
            stock_status = f"You have <span class='highlight danger'>{out_of_stock_count} item(s)</span> out of stock."
        else: # If also low stock
            stock_status += f" And <span class='highlight danger'>{out_of_stock_count} item(s)</span> out of stock."

    if expiring_30d_count > 0:
        if stock_status == "All stock levels are looking good today": # If only expiring
            stock_status = f"<span class='highlight warning'>{expiring_30d_count} product(s)</span> expiring within 30 days."
        else: # If also low stock or out of stock
            stock_status += f" Also, <span class='highlight warning'>{expiring_30d_count} product(s)</span> expiring within 30 days."

    # Stock Forecasting - top products nearing depletion
    forecast_products = []
    # Get products with stock > 0 that have transaction history
    forecast_candidates = product_query.filter(
        Product.quantity > 0
    ).order_by(Product.quantity).limit(20).all()
    
    for p in forecast_candidates:
        forecast = calculate_stock_forecast(p, analysis_days=60)
        if forecast['has_forecast'] and forecast['days_until_depletion'] is not None:
            forecast_products.append({
                'product': p,
                'forecast': forecast
            })
    
    # Sort by days until depletion (most urgent first) and limit to 5
    forecast_products.sort(key=lambda x: x['forecast']['days_until_depletion'])
    forecast_products = forecast_products[:5]

    return render_template(
        'shared/index.html',
        total_inventory=total_inventory,
        pending_requisitions=pending_requisitions,
        low_stock_count=low_stock_count,
        out_of_stock_count=out_of_stock_count,
        expiring_30d=expiring_30d_count,
        recent_logs=recent_logs,
        low_stock_items=low_stock_items,
        favorite_products=favorite_products,
        expiring_products=expiring_products,
        expired_products_top5=expired_products_top5,
        stock_status=stock_status,
        now=now_ph,
        top_product_labels=top_product_labels,
        top_product_quantities=top_product_quantities,
        labels=labels,
        added_data=added_data,
        removed_data=removed_data,
        expiry_view=expiry_view,
        forecast_products=forecast_products
    )


@main.route('/send_weekly_report', methods=['POST'])
@login_required
@admin_required
def send_weekly_report():
    try:
        now_pht = datetime.now(ZoneInfo("Asia/Manila"))
        report_date = now_pht.strftime('%B %d, %Y')
        
        # Send report only to the current user
        current_user_only = [current_user]
        
        if not current_user_only:
            flash('No user found to send the report.', 'error')
            return redirect(url_for('main.dashboard'))
            
        today = now_pht.date()
        
        # For Company-Admin users, filter data by their company
        if current_user.role == 'Company-Admin' and hasattr(current_user, 'company_id'):
            # Filter products by company using the new low stock logic
            low_stock_items = Product.query.filter(
                Product.quantity > 0,
                Product.company_id == current_user.company_id,
                db.or_(
                    db.and_(Product.reorder_level > 0, Product.quantity <= Product.reorder_level),
                    db.and_(Product.reorder_level == 0, Product.initial_quantity > 0, 
                           Product.quantity <= (Product.initial_quantity * (Product.low_stock_threshold / 100)))
                )
            ).all()
            
            zero_stock_items = Product.query.filter(
                Product.quantity == 0,
                Product.company_id == current_user.company_id
            ).all()
            
            # Filter expired products by company
            expired_products = db.session.query(Product).join(WarehouseProductBatch).filter(
                db.and_(
                    WarehouseProductBatch.exp_date <= today, 
                    WarehouseProductBatch.quantity > 0,
                    Product.company_id == current_user.company_id
                )
            ).distinct().all()
            
            # Filter expiring products by company
            three_months_from_now = today + timedelta(days=90)
            expiring_3months = []
            products_with_batches = db.session.query(Product).join(WarehouseProductBatch).filter(
                Product.company_id == current_user.company_id
            ).distinct().all()
            
            for product in products_with_batches:
                batches = WarehouseProductBatch.query.filter_by(product_id=product.id).all()
                if batches:
                    has_future_batches = False
                    has_expiring_batches = False
                    for batch in batches:
                        if batch.quantity > 0:
                            if batch.exp_date > today:
                                has_future_batches = True
                                if batch.exp_date <= three_months_from_now:
                                    has_expiring_batches = True
                                    break
                    if has_expiring_batches and has_future_batches:
                        expiring_3months.append(product)
        else:
            # For SYS-Admin and WH-Admin, show all data (existing behavior) with new low stock logic
            low_stock_items = Product.query.filter(
                Product.quantity > 0,
                db.or_(
                    db.and_(Product.reorder_level > 0, Product.quantity <= Product.reorder_level),
                    db.and_(Product.reorder_level == 0, Product.initial_quantity > 0, 
                           Product.quantity <= (Product.initial_quantity * (Product.low_stock_threshold / 100)))
                )
            ).all()
            
            zero_stock_items = Product.query.filter(Product.quantity == 0).all()
            
            expired_products = db.session.query(Product).join(WarehouseProductBatch).filter(
                db.and_(WarehouseProductBatch.exp_date <= today, WarehouseProductBatch.quantity > 0)
            ).distinct().all()
            
            three_months_from_now = today + timedelta(days=90)
            expiring_3months = []
            products_with_batches = db.session.query(Product).join(WarehouseProductBatch).distinct().all()
            
            for product in products_with_batches:
                batches = WarehouseProductBatch.query.filter_by(product_id=product.id).all()
                if batches:
                    has_future_batches = False
                    has_expiring_batches = False
                    for batch in batches:
                        if batch.quantity > 0:
                            if batch.exp_date > today:
                                has_future_batches = True
                                if batch.exp_date <= three_months_from_now:
                                    has_expiring_batches = True
                                    break
                    if has_expiring_batches and has_future_batches:
                        expiring_3months.append(product)
        
        def format_report(data, report_date):
            low_stock_html = ""
            for product in data['low_stock_items']:
                low_stock_html += f"<tr><td>{product.name}</td><td>{product.quantity} {product.uom}</td><td>{product.reorder_level} {product.uom}</td></tr>"
            
            zero_stock_html = ""
            for product in data['zero_stock_items']:
                zero_stock_html += f"<tr><td>{product.name}</td><td>{product.uom}</td><td>{product.account_title}</td></tr>"
            
            expired_html = ""
            for product in data['expired_products']:
                expired_qty = sum(batch.quantity for batch in product.warehouse_batches if batch.exp_date <= datetime.now(ZoneInfo("Asia/Manila")).date() and batch.quantity > 0)
                expired_html += f"<tr><td>{product.name}</td><td>{expired_qty} {product.uom}</td><td>{product.account_title}</td></tr>"
            
            expiring_html = ""
            for product in data['expiring_3months']:
                today = datetime.now(ZoneInfo("Asia/Manila")).date()
                three_months_from_now = today + timedelta(days=90)
                expiring_batches = [batch for batch in product.warehouse_batches if batch.quantity > 0 and batch.exp_date > today and batch.exp_date <= three_months_from_now]
                if expiring_batches:
                    earliest_batch = min(expiring_batches, key=lambda x: x.exp_date)
                    days_left = (earliest_batch.exp_date - today).days
                    expiring_html += f"<tr><td>{product.name}</td><td>{days_left} days</td><td>{product.account_title}</td></tr>"
            
            # Add company information to the report title for Company-Admin users
            report_title = "IcebergINV Daily Report"
            if current_user.role == 'Company-Admin' and hasattr(current_user, 'company') and current_user.company:
                report_title = f"{current_user.company.name} - {report_title}"
            
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .container {{ max-width: 800px; margin: 0 auto; padding: 20px; }}
                    .header {{ background: #2c3e50; color: white; padding: 15px; text-align: center; border-radius: 5px; }}
                    .header h1 {{ font-size: 1.5em; margin: 0 0 10px 0; }}
                    .header p {{ font-size: 0.9em; margin: 0; opacity: 0.9; }}
                    .section {{ margin: 20px 0; padding: 15px; border: 1px solid #ddd; border-radius: 5px; }}
                    .section h3 {{ color: #2c3e50; margin-top: 0; font-size: 1.2em; }}
                    table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
                    th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }}
                    th {{ background: #f8f9fa; font-weight: bold; }}
                    .warning {{ color: #e74c3c; }}
                    .info {{ color: #3498db; }}
                    .success {{ color: #27ae60; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>📊 {report_title}</h1>
                        <p>Date: {report_date}</p>
                    </div>
                    <div class="section">
                        <h3>⚠️ Low Stock Items ({len(data['low_stock_items'])} items)</h3>
                        <table><thead><tr><th>Product Name</th><th>Current Stock</th><th>Reorder Level</th></tr></thead><tbody>{low_stock_html}</tbody></table>
                    </div>
                    <div class="section">
                        <h3>🚫 Out of Stock Items ({len(data['zero_stock_items'])} items)</h3>
                        <table><thead><tr><th>Product Name</th><th>Unit</th><th>Account</th></tr></thead><tbody>{zero_stock_html}</tbody></table>
                    </div>
                    <div class="section">
                        <h3>❌ Expired Products ({len(data['expired_products'])} items)</h3>
                        <table><thead><tr><th>Product Name</th><th>Total Expired</th><th>Account</th></tr></thead><tbody>{expired_html}</tbody></table>
                    </div>
                    <div class="section">
                        <h3>⏰ Expiring Within 3 Months ({len(data['expiring_3months'])} items)</h3>
                        <table><thead><tr><th>Product Name</th><th>Days Left</th><th>Account</th></tr></thead><tbody>{expiring_html}</tbody></table>
                    </div>
                    <div class="section">
                        <p><strong>Report generated on:</strong> {datetime.now(ZoneInfo("Asia/Manila")).strftime('%Y-%m-%d %H:%M:%S %Z')}</p>
                        <p><em>This is an automated daily report from IcebergINV system.</em></p>
                    </div>
                </div>
            </body>
            </html>
            """
            return html_content
        
        report_data = {
            'low_stock_items': low_stock_items,
            'zero_stock_items': zero_stock_items,
            'expired_products': expired_products,
            'expiring_3months': expiring_3months
        }
        
        report_content = format_report(report_data, report_date)
        from extensions import mail
        
        sent_count = 0
        for user in current_user_only:
            # Customize subject for Company-Admin users
            if current_user.role == 'Company-Admin' and hasattr(current_user, 'company') and current_user.company:
                subject = f"{current_user.company.name} - IcebergINV Daily Report - {report_date}"
            else:
                subject = f"IcebergINV Daily Report - {report_date}"
                
            msg = Message(
                subject=subject,
                recipients=[user.email],
                html=report_content
            )
            try:
                mail.send(msg)
                sent_count += 1
            except Exception as e:
                print(f"Error sending to {user.email}: {str(e)}")
        
        if sent_count:
            flash(f'Daily report sent to your email.', 'success')
        else:
            flash('Failed to send daily report.', 'error')
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
    return redirect(url_for('main.dashboard'))


@main.route('/send_purchaser_report', methods=['POST'])
@login_required
def send_purchaser_report():
    """Send a report to all Purchaser users"""
    try:
        # Only Purchaser users can send this report
        if current_user.role != 'Purchaser':
            flash('Access denied. Only Purchaser users can send this report.', 'error')
            return redirect(url_for('main.dashboard'))
        
        now_pht = datetime.now(ZoneInfo("Asia/Manila"))
        report_date = now_pht.strftime('%B %d, %Y')
        
        # Send report only to the current user
        current_user_only = [current_user]
        if not current_user_only:
            flash('No user found to send the report.', 'error')
            return redirect(url_for('main.dashboard'))
        
        today = now_pht.date()
        
        # Get low stock items using raw SQL logic instead of the property
        low_stock_items = Product.query.filter(
            Product.quantity > 0,  # Exclude out-of-stock items
            db.or_(
                db.and_(Product.reorder_level > 0, Product.quantity <= Product.reorder_level),
                db.and_(Product.reorder_level == 0, Product.initial_quantity > 0, 
                       Product.quantity <= (Product.initial_quantity * (Product.low_stock_threshold / 100)))
            )
        ).all()
        
        # Get zero stock items
        zero_stock_items = Product.query.filter(Product.quantity == 0).all()
        
        # Get expired products
        expired_products = db.session.query(Product).join(WarehouseProductBatch).filter(
            db.and_(WarehouseProductBatch.exp_date <= today, WarehouseProductBatch.quantity > 0)
        ).distinct().all()
        
        # Get products expiring in 3 months
        three_months_from_now = today + timedelta(days=90)
        expiring_3months = []
        products_with_batches = db.session.query(Product).join(WarehouseProductBatch).distinct().all()
        
        for product in products_with_batches:
            batches = WarehouseProductBatch.query.filter_by(product_id=product.id).all()
            if batches:
                has_future_batches = False
                has_expiring_batches = False
                for batch in batches:
                    if batch.quantity > 0:
                        if batch.exp_date > today:
                            has_future_batches = True
                            if batch.exp_date <= three_months_from_now:
                                has_expiring_batches = True
                                break
                if has_expiring_batches and has_future_batches:
                    expiring_3months.append(product)
        
        def format_purchaser_report(data, report_date):
            low_stock_html = ""
            for product in data['low_stock_items']:
                low_stock_html += f"<tr><td>{product.name}</td><td>{product.quantity} {product.uom}</td><td>{product.reorder_level} {product.uom}</td></tr>"
            
            zero_stock_html = ""
            for product in data['zero_stock_items']:
                zero_stock_html += f"<tr><td>{product.name}</td><td>{product.uom}</td><td>{product.account_title}</td></tr>"
            
            expired_html = ""
            for product in data['expired_products']:
                expired_qty = sum(batch.quantity for batch in product.warehouse_batches if batch.exp_date <= datetime.now(ZoneInfo("Asia/Manila")).date() and batch.quantity > 0)
                expired_html += f"<tr><td>{product.name}</td><td>{expired_qty} {product.uom}</td><td>{product.account_title}</td></tr>"
            
            expiring_html = ""
            for product in data['expiring_3months']:
                today = datetime.now(ZoneInfo("Asia/Manila")).date()
                three_months_from_now = today + timedelta(days=90)
                expiring_batches = [batch for batch in product.warehouse_batches if batch.quantity > 0 and batch.exp_date > today and batch.exp_date <= three_months_from_now]
                if expiring_batches:
                    earliest_batch = min(expiring_batches, key=lambda x: x.exp_date)
                    days_left = (earliest_batch.exp_date - today).days
                    expiring_html += f"<tr><td>{product.name}</td><td>{days_left} days</td><td>{product.account_title}</td></tr>"
            
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset=\"UTF-8\">
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .container {{ max-width: 800px; margin: 0 auto; padding: 20px; }}
                    .header {{ background: #f39c12; color: white; padding: 15px; text-align: center; border-radius: 5px; }}
                    .header h1 {{ font-size: 1.5em; margin: 0 0 10px 0; }}
                    .header p {{ font-size: 0.9em; margin: 0; opacity: 0.9; }}
                    .section {{ margin: 20px 0; padding: 15px; border: 1px solid #ddd; border-radius: 5px; }}
                    .section h3 {{ color: #2c3e50; margin-top: 0; font-size: 1.2em; }}
                    table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
                    th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }}
                    th {{ background: #f8f9fa; font-weight: bold; }}
                    .warning {{ color: #e74c3c; }}
                    .info {{ color: #3498db; }}
                    .success {{ color: #27ae60; }}
                </style>
            </head>
            <body>
                <div class=\"container\">
                    <div class=\"header\">
                        <h1>📊 IcebergINV Purchaser Report</h1>
                        <p>Date: {report_date}</p>
                        <p>Sent by: {current_user.full_name}</p>
                    </div>
                    <div class=\"section\">
                        <h3>⚠️ Low Stock Items ({len(data['low_stock_items'])} items)</h3>
                        <table><thead><tr><th>Product Name</th><th>Current Stock</th><th>Reorder Level</th></tr></thead><tbody>{low_stock_html}</tbody></table>
                    </div>
                    <div class=\"section\">
                        <h3>🚫 Out of Stock Items ({len(data['zero_stock_items'])} items)</h3>
                        <table><thead><tr><th>Product Name</th><th>Unit</th><th>Account</th></tr></thead><tbody>{zero_stock_html}</tbody></table>
                    </div>
                    <div class=\"section\">
                        <h3>❌ Expired Products ({len(data['expired_products'])} items)</h3>
                        <table><thead><tr><th>Product Name</th><th>Total Expired</th><th>Account</th></tr></thead><tbody>{expired_html}</tbody></table>
                    </div>
                    <div class=\"section\">
                        <h3>⏰ Expiring Within 3 Months ({len(data['expiring_3months'])} items)</h3>
                        <table><thead><tr><th>Product Name</th><th>Days Left</th><th>Account</th></tr></thead><tbody>{expiring_html}</tbody></table>
                    </div>
                    <div class=\"section\">
                        <p><strong>Report generated on:</strong> {datetime.now(ZoneInfo("Asia/Manila")).strftime('%Y-%m-%d %H:%M:%S %Z')}</p>
                        <p><em>This is a Purchaser report from IcebergINV system.</em></p>
                    </div>
                </div>
            </body>
            </html>
            """
            return html_content
        
        report_data = {
            'low_stock_items': low_stock_items,
            'zero_stock_items': zero_stock_items,
            'expired_products': expired_products,
            'expiring_3months': expiring_3months
        }
        
        report_content = format_purchaser_report(report_data, report_date)
        
        from extensions import mail
        sent_count = 0
        
        for user in current_user_only:
            subject = f"IcebergINV Purchaser Report - {report_date}"
            msg = Message(
                subject=subject,
                recipients=[user.email],
                html=report_content
            )
            try:
                mail.send(msg)
                sent_count += 1
            except Exception as e:
                print(f"Error sending to {user.email}: {str(e)}")
        
        if sent_count:
            flash(f'Purchaser report sent to your email.', 'success')
        else:
            flash('Failed to send purchaser report.', 'error')
            
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
    
    return redirect(url_for('main.dashboard'))

