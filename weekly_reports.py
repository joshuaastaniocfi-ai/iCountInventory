#!/usr/bin/env python3
"""
Weekly Email Reports System
This script generates and sends weekly reports to SYS-Admin and WH-Admin users
"""

import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import Flask app and database
from app import create_app
from extensions import db
from models import Product, WarehouseProductBatch, StoreProductBatch, User, ActivityLog, StockAudit, Requisition
from helpers import log_activity

def generate_weekly_report():
    """Generate weekly inventory and activity report"""
    
    # Create Flask app context
    app = create_app()
    
    with app.app_context():
        try:
            # Get current date and time in PHT
            now_pht = datetime.now(ZoneInfo("Asia/Manila"))
            
            # Check if it's Monday 8:00 AM PHT (entire 8 AM hour)
            if not should_send_weekly_report(now_pht):
                print(f"⏰ Not Monday 8:00 AM PHT yet. Current time: {now_pht.strftime('%A %H:%M %Z')}")
                print("📧 Weekly reports will only be sent on Mondays during the 8 AM hour (8:00 AM - 8:59 AM)")
                return
            
            print(f"✅ It's Monday 8:00 AM PHT - proceeding with weekly report generation")
            
            # Calculate week start (previous Monday)
            week_start = get_previous_monday(now_pht)
            
            print(f"📊 Generating weekly report for week of {week_start.strftime('%Y-%m-%d')} to {now_pht.strftime('%Y-%m-%d')}")
            
            # Get all admin users
            admin_users = User.query.filter(User.role.in_(['SYS-Admin', 'WH-Admin'])).all()
            
            if not admin_users:
                print("❌ No admin users found")
                return
            
            # Collect report data
            report_data = collect_report_data(week_start, now_pht)
            
            # Debug: Print collected data counts
            print(f"📊 Report Data Collected:")
            print(f"   - Low Stock Items: {len(report_data['low_stock_items'])}")
            print(f"   - Zero Stock Items: {len(report_data['zero_stock_items'])}")
            print(f"   - Expired Products: {len(report_data['expired_products'])}")
            print(f"   - Expiring in 3 Months: {len(report_data['expiring_3months'])}")
            
            # Generate report content
            report_content = format_report(report_data, week_start, now_pht)
            
            # Send email to each admin
            for admin in admin_users:
                send_weekly_report_email(admin, report_content, week_start, now_pht)
            
            print(f"✅ Weekly reports sent to {len(admin_users)} admin users")
            
        except Exception as e:
            print(f"❌ Error generating weekly report: {str(e)}")
            import traceback
            traceback.print_exc()

def should_send_weekly_report(now_pht):
    """Check if it's Monday 8:00 AM PHT (entire 8 AM hour)"""
    # Check if it's Monday (0 = Monday in Python)
    if now_pht.weekday() != 0:
        return False
    
    # Check if it's during the 8 AM hour (8:00 AM to 8:59 AM)
    return now_pht.hour == 8

def get_previous_monday(now_pht):
    """Get the previous Monday date"""
    days_since_monday = now_pht.weekday()
    if days_since_monday == 0:  # If it's Monday, use today
        return now_pht.replace(hour=0, minute=0, second=0, microsecond=0)
    else:  # Go back to previous Monday
        return (now_pht - timedelta(days=days_since_monday)).replace(hour=0, minute=0, second=0, microsecond=0)

def collect_report_data(week_start, week_end):
    """Collect data for the weekly report"""
    
    # Get current date in PHT
    now_pht = datetime.now(ZoneInfo("Asia/Manila"))
    today = now_pht.date()
    
    # Low stock items (all, not limited) using raw SQL logic instead of the is_low_stock property
    low_stock_items = Product.query.filter(
        Product.quantity > 0,  # Exclude out-of-stock items
        db.or_(
            db.and_(Product.reorder_level > 0, Product.quantity <= Product.reorder_level),
            db.and_(Product.reorder_level == 0, Product.initial_quantity > 0, 
                   Product.quantity <= (Product.initial_quantity * (Product.low_stock_threshold / 100)))
        )
    ).all()
    
    # Zero stock items (all, not limited)
    zero_stock_items = Product.query.filter(
        Product.quantity == 0
    ).all()
    
    # Expired products (all, not limited) - using same logic as products.py
    expired_products = db.session.query(Product).join(WarehouseProductBatch).filter(
        db.and_(
            WarehouseProductBatch.exp_date <= today,  # <= today means expired (including today's expiry)
            WarehouseProductBatch.quantity > 0
        )
    ).distinct().all()
    
    print(f"🔍 Found {len(expired_products)} expired products")
    
    # Debug: Show expired product details
    for product in expired_products:
        expired_batches = [batch for batch in product.batches if batch.exp_date <= today and batch.quantity > 0]
        total_expired_qty = sum(batch.quantity for batch in expired_batches)
        print(f"   ❌ {product.name}: {total_expired_qty} {product.uom} expired (batches: {len(expired_batches)})")
    
    # Expiring products within 3 months (excluding already expired)
    # This should include products that have batches expiring in 3 months but are not fully expired
    three_months_from_now = today + timedelta(days=90)
    
    # Get products that have at least one batch expiring within 3 months
    # but exclude products that are completely expired
    expiring_3months = []
    
    # Get all products with batches
    products_with_batches = db.session.query(Product).join(WarehouseProductBatch).distinct().all()
    
    print(f"🔍 Checking {len(products_with_batches)} products with batches for expiring within 3 months")
    
    for product in products_with_batches:
        # Get all batches for this product
        batches = WarehouseProductBatch.query.filter_by(product_id=product.id).all()
        
        if batches:
            # Check if product has any non-expired batches expiring within 3 months
            has_future_batches = False
            has_expiring_batches = False
            
            for batch in batches:
                if batch.quantity > 0:  # Only consider batches with stock
                    if batch.exp_date > today:  # Not expired yet
                        has_future_batches = True
                        if batch.exp_date <= three_months_from_now:  # Expiring within 3 months
                            has_expiring_batches = True
                            break
            
            # Include product if it has expiring batches within 3 months
            # and has at least some future (non-expired) batches
            if has_expiring_batches and has_future_batches:
                expiring_3months.append(product)
                print(f"   ✅ {product.name}: has batches expiring within 3 months")
    
    print(f"🔍 Found {len(expiring_3months)} products expiring within 3 months")
    
    return {
        'low_stock_items': low_stock_items,
        'zero_stock_items': zero_stock_items,
        'expired_products': expired_products,
        'expiring_3months': expiring_3months
    }

def format_report(data, week_start, week_end):
    """Format the report data into HTML email content"""
    
    # Format low stock items
    low_stock_html = ""
    for product in data['low_stock_items']:
        percentage = (product.quantity / product.initial_quantity * 100) if product.initial_quantity > 0 else 0
        low_stock_html += f"<tr><td>{product.name}</td><td>{product.quantity}/{product.initial_quantity} {product.uom}</td><td>{percentage:.1f}%</td></tr>"
    
    # Format zero stock items
    zero_stock_html = ""
    for product in data['zero_stock_items']:
        zero_stock_html += f"<tr><td>{product.name}</td><td>{product.uom}</td><td>{product.account_title}</td></tr>"
    
    # Format expired products
    expired_html = ""
    for product in data['expired_products']:
        # Get total expired quantity from batches
        expired_qty = sum(batch.quantity for batch in product.batches if batch.exp_date <= datetime.now(ZoneInfo("Asia/Manila")).date() and batch.quantity > 0)
        expired_html += f"<tr><td>{product.name}</td><td>{expired_qty} {product.uom}</td><td>{product.account_title}</td></tr>"
    
    # Format expiring products within 3 months
    expiring_html = ""
    for product in data['expiring_3months']:
        # Get days until expiry for the earliest expiring batch within 3 months
        today = datetime.now(ZoneInfo("Asia/Manila")).date()
        three_months_from_now = today + timedelta(days=90)
        
        # Find batches expiring within 3 months
        expiring_batches = [batch for batch in product.batches 
                           if batch.quantity > 0 
                           and batch.exp_date > today 
                           and batch.exp_date <= three_months_from_now]
        
        if expiring_batches:
            # Get the earliest expiring batch
            earliest_batch = min(expiring_batches, key=lambda x: x.exp_date)
            days_left = (earliest_batch.exp_date - today).days
            expiring_html += f"<tr><td>{product.name}</td><td>{days_left} days</td><td>{product.account_title}</td></tr>"
    
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
                <h1>📊 IcebergINV Weekly Report</h1>
                <p>Week of {week_start.strftime('%B %d, %Y')} to {week_end.strftime('%B %d, %Y')}</p>
            </div>
            
            <div class="section">
                <h3>⚠️ Low Stock Items ({len(data['low_stock_items'])} items)</h3>
                <table>
                    <thead>
                        <tr><th>Product Name</th><th>Current/Initial Stock</th><th>Stock Level</th></tr>
                    </thead>
                    <tbody>
                        {low_stock_html}
                    </tbody>
                </table>
            </div>
            
            <div class="section">
                <h3>🚫 Out of Stock Items ({len(data['zero_stock_items'])} items)</h3>
                <table>
                    <thead>
                        <tr><th>Product Name</th><th>Unit</th><th>Account</th></tr>
                    </thead>
                    <tbody>
                        {zero_stock_html}
                    </tbody>
                </table>
            </div>
            
            <div class="section">
                <h3>❌ Expired Products ({len(data['expired_products'])} items)</h3>
                <table>
                    <thead>
                        <tr><th>Product Name</th><th>Total Expired</th><th>Account</th></tr>
                    </thead>
                    <tbody>
                        {expired_html}
                    </tbody>
                </table>
            </div>
            
            <div class="section">
                <h3>⏰ Expiring Within 3 Months ({len(data['expiring_3months'])} items)</h3>
                <table>
                    <thead>
                        <tr><th>Product Name</th><th>Days Left</th><th>Account</th></tr>
                    </thead>
                    <tbody>
                        {expiring_html}
                    </tbody>
                </table>
            </div>
            
            <div class="section">
                <p><strong>Report generated on:</strong> {datetime.now(ZoneInfo("Asia/Manila")).strftime('%Y-%m-%d %H:%M:%S %Z')}</p>
                <p><em>This is an automated weekly report from IcebergINV system.</em></p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return html_content

def send_weekly_report_email(admin_user, report_content, week_start, week_end):
    """Send the weekly report email to an admin user"""
    
    try:
        from flask_mail import Message
        
        # Get mail instance from Flask app
        from extensions import mail
        
        subject = f"IcebergINV Weekly Report - Week of {week_start.strftime('%B %d, %Y')}"
        
        msg = Message(
            subject=subject,
            recipients=[admin_user.email],
            html=report_content
        )
        
        # Send email
        mail.send(msg)
        
        print(f"✅ Email sent to {admin_user.email}")
        
        # Log the email sending
        log_activity(
            action="Weekly Report Sent",
            details=f"Weekly report sent to {admin_user.username} ({admin_user.email}) for week of {week_start.strftime('%Y-%m-%d')}"
        )
        
    except Exception as e:
        print(f"❌ Error sending email to {admin_user.email}: {str(e)}")

if __name__ == "__main__":
    print("🚀 Starting weekly report generation...")
    
    # Show current time in both UTC and PHT
    now_utc = datetime.now(ZoneInfo("UTC"))
    now_pht = datetime.now(ZoneInfo("Asia/Manila"))
    
    print(f"🌍 Current UTC time: {now_utc.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"🇵🇭 Current PHT time: {now_pht.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"📅 Day of week: {now_pht.strftime('%A')}")
    
    generate_weekly_report()
    print("✨ Weekly report generation completed!")
