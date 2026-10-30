# Standard library imports
import barcode
from barcode.writer import ImageWriter
from datetime import datetime, timedelta
from functools import wraps
from zoneinfo import ZoneInfo
import os

# Third-party imports
from flask import redirect, url_for, flash, current_app
from flask_login import current_user

# Local imports
from extensions import db
from models import User, Product, ActivityLog, WarehouseProductBatch, StoreProductBatch, Notification


def is_mobile_device(user_agent):
    """Check if the user agent indicates a mobile device"""
    if not user_agent:
        return False
    
    user_agent_lower = user_agent.lower()
    mobile_keywords = [
        'mobile', 'android', 'iphone', 'ipad', 'blackberry', 
        'windows phone', 'opera mini', 'mobile safari', 'mobile chrome'
    ]
    
    is_mobile = any(keyword in user_agent_lower for keyword in mobile_keywords)
    
    return is_mobile


def get_redirect_url_for_user(user, user_agent):
    """Determine the appropriate redirect URL based on user role and device type"""
    is_mobile = is_mobile_device(user_agent)
    
    if user.role == 'User':
        return url_for('requisitions.store_inventory', login_success='true')
    elif user.role in ['SYS-Admin', 'WH-Admin', 'Company-Admin']:
        if is_mobile:
            return url_for('scanner.mobile_scanner')
        else:
            return url_for('main.dashboard')
    else:
        return url_for('main.dashboard')


def user_redirect_to_requisition(view_func):
    """Decorator to redirect User role to store inventory"""
    @wraps(view_func)
    def decorated_view(*args, **kwargs):
        if current_user.is_authenticated and current_user.role == 'User':
            return redirect(url_for('requisitions.store_inventory'))
        return view_func(*args, **kwargs)
    return decorated_view


def admin_required(view_func):
    """Decorator to require admin privileges"""
    @wraps(view_func)
    def decorated_view(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if getattr(current_user, 'role', None) not in ['SYS-Admin', 'WH-Admin', 'Company-Admin']:
            flash('Access denied. SYS-Admin, WH-Admin, or Company-Admin privileges required.', 'error')
            return redirect(url_for('main.dashboard'))
        return view_func(*args, **kwargs)
    return decorated_view


def sys_admin_required(view_func):
    """Decorator to require SYS-Admin privileges only"""
    @wraps(view_func)
    def decorated_view(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if getattr(current_user, 'role', None) != 'SYS-Admin':
            flash('Access denied. SYS-Admin privileges required.', 'error')
            return redirect(url_for('main.dashboard'))
        return view_func(*args, **kwargs)
    return decorated_view


def edit_delete_required(view_func):
    """Decorator to require SYS-Admin or Company-Admin privileges for edit/delete operations (excludes WH-Admin)"""
    @wraps(view_func)
    def decorated_view(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if getattr(current_user, 'role', None) not in ['SYS-Admin', 'Company-Admin']:
            flash('Access denied. SYS-Admin or Company-Admin privileges required for this operation.', 'error')
            return redirect(url_for('main.dashboard'))
        return view_func(*args, **kwargs)
    return decorated_view


def generate_barcode_image(code, company_id=None):
    """
    Generate and save barcode PNG image for a given barcode string.
    Saves to:
      - static/product_barcodes/company_{company_id}/{code}.png (if company_id is provided or current_user has one)
      - static/product_barcodes/{code}.png (universal root fallback)
    Uses EAN-13 when code is 12 or 13 digits; falls back to Code128 otherwise.
    """
    import os
    import traceback
    if not code:
        return False
        
    code_str = str(code).strip()
    root_dir = os.path.join(current_app.root_path, 'static', 'product_barcodes')
    os.makedirs(root_dir, exist_ok=True)
    
    target_dirs = [root_dir]
    eff_comp = company_id
    if eff_comp is None and hasattr(current_user, 'company_id') and current_user and current_user.company_id:
        eff_comp = current_user.company_id
        
    if eff_comp:
        comp_dir = os.path.join(root_dir, f'company_{eff_comp}')
        os.makedirs(comp_dir, exist_ok=True)
        target_dirs.append(comp_dir)
        
    try:
        writer = ImageWriter()
        if code_str.isdigit() and len(code_str) in (12, 13):
            ean_code = code_str[:12]
            bc_obj = barcode.get('ean13', ean_code, writer=writer)
        else:
            bc_obj = barcode.get('code128', code_str, writer=writer)
            
        for d in target_dirs:
            target_base = os.path.join(d, code_str)
            bc_obj.save(target_base)
        return True
    except Exception as e:
        print(f"Warning: Could not generate barcode image for {code_str}: {e}")
        print(f"Full traceback: {traceback.format_exc()}")
        return False


def generate_barcode(company_id=None):
    """Generate a unique barcode for new products and create its image files."""
    base = current_app.config.get('BARCODE_BASE', "12082016")
    
    # Get the highest existing barcode number to ensure uniqueness
    existing_products = Product.query.all()
    max_number = 0
    
    for product in existing_products:
        try:
            if product.barcode and product.barcode.startswith(base):
                number_part = product.barcode[len(base):]
                if number_part.isdigit():
                    max_number = max(max_number, int(number_part))
        except (ValueError, AttributeError):
            continue
    
    # Generate next unique number
    next_number = max_number + 1
    code = base + str(next_number).zfill(4)
    
    eff_comp = company_id
    if eff_comp is None and hasattr(current_user, 'company_id') and current_user and current_user.company_id:
        eff_comp = current_user.company_id
        
    generate_barcode_image(code, company_id=eff_comp)
    return code


def ensure_product_barcode(product):
    """Ensure a product has a valid barcode in DB and its image exists on disk."""
    changed = False
    if not product.barcode:
        product.barcode = generate_barcode(company_id=product.company_id)
        changed = True
        
    root_dir = os.path.join(current_app.root_path, 'static', 'product_barcodes')
    root_file = os.path.join(root_dir, f'{product.barcode}.png')
    comp_file = os.path.join(root_dir, f'company_{product.company_id}', f'{product.barcode}.png') if product.company_id else None
    
    if not os.path.exists(root_file) or (comp_file and not os.path.exists(comp_file)):
        generate_barcode_image(product.barcode, company_id=product.company_id)
        
    return changed


def ensure_all_product_barcodes():
    """Verify all products in the database have barcodes and images. Returns count of new barcodes assigned."""
    products = Product.query.all()
    fixed_barcodes = 0
    base = current_app.config.get('BARCODE_BASE', "12082016")
    
    max_num = 0
    for p in products:
        if p.barcode and p.barcode.startswith(base):
            part = p.barcode[len(base):]
            if part.isdigit():
                max_num = max(max_num, int(part))
                
    for p in products:
        if not p.barcode:
            max_num += 1
            p.barcode = base + str(max_num).zfill(4)
            fixed_barcodes += 1
        ensure_product_barcode(p)
        
    if fixed_barcodes > 0:
        db.session.commit()
        
    return fixed_barcodes


def generate_sub_barcode(product_barcode=None, exp_date=None, db_connection=None, company_id=None):
    """Sub-barcode and batch barcode image generation have been disabled."""
    return None

def log_activity(action, details=None):
    """Log an activity to the database"""
    # Get current time in PHT
    current_time = datetime.now(ZoneInfo("Asia/Manila"))
    log = ActivityLog(
        action=action,
        details=details,
        timestamp=current_time
    )
    
    # Assign company if user is logged in and has a company
    if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated:
        if hasattr(current_user, 'company_id') and current_user.company_id:
            log.company_id = current_user.company_id
    
    db.session.add(log)
    db.session.commit()


def assign_company(record):
    """Assign current user's company to a new record"""
    if hasattr(current_user, 'company_id') and current_user.company_id:
        record.company_id = current_user.company_id
    return record


def get_company_upload_directory(company_id, directory_type='uploads'):
    """Get company-specific directory path for uploads or reports"""
    if directory_type == 'uploads':
        return os.path.join(current_app.root_path, 'uploads', f'company_{directory_id}')
    elif directory_type == 'reports':
        return os.path.join(current_app.root_path, 'reports', f'company_{directory_id}')
    else:
        raise ValueError("directory_type must be 'uploads' or 'reports'")


def calculate_stock_forecast(product, analysis_days=60):
    """
    Calculate stock depletion forecast based on historical consumption.
    
    Args:
        product: Product ORM object
        analysis_days: Number of days of history to analyze (default 60)
        
    Returns:
        dict with keys:
            - daily_consumption: Average daily consumption rate
            - days_until_depletion: Estimated days until stock runs out
            - projected_depletion_date: Estimated date of stock-out (string) or None
            - total_consumed: Total quantity consumed in analysis period
            - analysis_days: Actual days analyzed
            - has_forecast: Whether forecast is reliable
    """
    from models import ProductHistory
    
    today = datetime.now(ZoneInfo("Asia/Manila")).date()
    cutoff = today - timedelta(days=analysis_days)
    
    # Get all TRANS OUT records within the analysis period
    out_records = ProductHistory.query.filter(
        ProductHistory.product_id == product.id,
        ProductHistory.trxn_code == 'TRANS OUT',
        ProductHistory.trxn_date >= cutoff
    ).all()
    
    total_consumed = sum(r.quantity_out for r in out_records)
    
    if total_consumed <= 0 or product.quantity <= 0:
        return {
            'daily_consumption': 0,
            'days_until_depletion': None,
            'projected_depletion_date': None,
            'total_consumed': total_consumed,
            'analysis_days': analysis_days,
            'has_forecast': False
        }
    
    # Calculate actual date range (first to last transaction)
    if out_records:
        first_date = min(r.trxn_date.date() for r in out_records)
        last_date = max(r.trxn_date.date() for r in out_records)
        actual_days = max((last_date - first_date).days, 1)
    else:
        actual_days = analysis_days
    
    daily_consumption = total_consumed / actual_days
    
    if daily_consumption > 0:
        days_until = int(product.quantity / daily_consumption)
        depletion_date = today + timedelta(days=days_until)
    else:
        days_until = None
        depletion_date = None
    
    return {
        'daily_consumption': round(daily_consumption, 4),
        'days_until_depletion': days_until,
        'projected_depletion_date': depletion_date.strftime('%Y-%m-%d') if depletion_date else None,
        'total_consumed': total_consumed,
        'analysis_days': actual_days,
        'has_forecast': daily_consumption > 0 and product.quantity > 0
    }


def create_notification(user_id, title, message=None, type='info', reference_type=None, reference_id=None):
    notif = Notification(
        user_id=user_id,
        title=title,
        message=message,
        type=type,
        reference_type=reference_type,
        reference_id=reference_id
    )
    db.session.add(notif)
    db.session.commit()
    return notif