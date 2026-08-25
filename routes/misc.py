# Standard library imports
from datetime import datetime, timedelta
import io
from pathlib import Path
from zoneinfo import ZoneInfo

# Third-party imports
from flask import Blueprint, render_template, request, redirect, url_for, flash, Response, current_app
from flask_login import login_required, current_user
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

# Local imports
from extensions import db
from models import Product, ProductHistory, WarehouseProductBatch, StoreProductBatch, Requisition, RequisitionItem, ActivityLog
from helpers import user_redirect_to_requisition, admin_required, log_activity

# Create blueprint with URL prefix
misc = Blueprint('misc', __name__, url_prefix='/misc')


@misc.route('/')
@login_required
@user_redirect_to_requisition
def misc_dashboard():
    """Misc dashboard with transaction history and barcode download"""
    today = datetime.now(ZoneInfo("Asia/Manila")).date()
    # Calculate one month ago from today
    one_month_ago = today - timedelta(days=30)
    
    return render_template('shared/misc_dashboard.html', today=today, one_month_ago=one_month_ago)


@misc.route('/transaction_history')
@login_required
@user_redirect_to_requisition
def transaction_history():
    """Transaction history download page (legacy - redirects to dashboard)"""
    return redirect(url_for('misc.misc_dashboard'))


@misc.route('/download_transaction_history', methods=['POST'])
@login_required
@admin_required
def download_transaction_history():
    """Download transaction history as Excel file"""
    try:
        # Get date range from form
        from_date_str = request.form.get('from_date')
        to_date_str = request.form.get('to_date')
        
        if not from_date_str or not to_date_str:
            flash('Please select both from and to dates.', 'error')
            return redirect(url_for('misc.transaction_history'))
        
        # Parse dates
        from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
        to_date = datetime.strptime(to_date_str, '%Y-%m-%d').date()
        
        if from_date > to_date:
            flash('From date cannot be later than to date.', 'error')
            return redirect(url_for('misc.transaction_history'))
        
        # Query transaction history within date range
        # Convert dates to datetime for proper comparison
        from_datetime = datetime.combine(from_date, datetime.min.time())
        to_datetime = datetime.combine(to_date, datetime.max.time())
        
        # Filter by company for Company-Admin users
        if current_user.role == 'Company-Admin' and current_user.company_id:
            # Company-Admin can only see their own company's transaction history
            history_records = ProductHistory.query.join(Product).filter(
                ProductHistory.trxn_date >= from_datetime,
                ProductHistory.trxn_date <= to_datetime,
                Product.company_id == current_user.company_id
            ).order_by(ProductHistory.product_id, ProductHistory.trxn_date).all()
        else:
            # SYS-Admin and WH-Admin can see all transaction history
            history_records = ProductHistory.query.filter(
                ProductHistory.trxn_date >= from_datetime,
                ProductHistory.trxn_date <= to_datetime
            ).order_by(ProductHistory.product_id, ProductHistory.trxn_date).all()
        
        if not history_records:
            flash('No transaction history found for the selected date range.', 'warning')
            return redirect(url_for('misc.transaction_history'))
        
        # Create Excel workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Transaction History"
        
        # Define styles
        header_font = Font(bold=True, color="FFFFFF", size=12)
        header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
        header_alignment = Alignment(horizontal="center", vertical="center")
        
        title_font = Font(bold=True, size=14)
        title_alignment = Alignment(horizontal="center", vertical="center")
        
        # Define borders
        thin_border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )
        
        # Write title
        ws.merge_cells('A1:G1')
        title_cell = ws.cell(row=1, column=1, value="ICEBERGS WAREHOUSE DETAILED INVENTORY")
        title_cell.font = title_font
        title_cell.alignment = title_alignment
        
        # Write date range
        ws.merge_cells('A2:G2')
        date_range = f"Period: {from_date.strftime('%b/%d/%Y')} to {to_date.strftime('%b/%d/%Y')}"
        date_cell = ws.cell(row=2, column=1, value=date_range)
        date_cell.font = Font(bold=True, size=12)
        date_cell.alignment = title_alignment
        
        # Write header row
        headers = [
            'item_description', 'trxn dt', 'trxn code', 'payee', 'IN', 'OUT', 'Total'
        ]
        
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=4, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            cell.border = thin_border
        
        # Group transactions by product
        current_row = 5
        current_product = None
        product_total = 0
        
        for record in history_records:
            # Get product details
            product = Product.query.get(record.product_id)
            if not product:
                continue
            
            # Format item description
            item_description = f"{product.name} ({product.uom or 'unit'})"
            
            # Format transaction date
            trxn_date = record.trxn_date.strftime('%m/%d/%Y')
            
            # Determine transaction code and payee
            if record.trxn_code == 'TRANS IN':
                trxn_code = 'TRANS IN'
                payee = record.payee or 'Icebergs Food Concepts, Inc.'
                in_qty = record.quantity_in
                out_qty = 0
                total = record.net_change
            elif record.trxn_code == 'TRANS OUT':
                trxn_code = 'TRANS OUT'
                payee = record.payee or 'ICEBERGS MARASBARAS'
                in_qty = 0
                out_qty = record.quantity_out
                total = record.net_change
            else:
                # Handle other transaction types
                trxn_code = record.trxn_code
                payee = record.payee or 'COOL ICE FOOD DESSERTS'
                in_qty = record.quantity_in if record.quantity_in else 0
                out_qty = record.quantity_out if record.quantity_out else 0
                total = record.net_change
            
            # Check if this is a new product (first transaction for this product)
            is_new_product = current_product != record.product_id
            
            # Write transaction row
            row_data = [
                item_description if is_new_product else '',  # Only show item description for first transaction
                trxn_date,
                trxn_code,
                payee,
                in_qty,
                out_qty,
                total
            ]
            
            for col, value in enumerate(row_data, 1):
                cell = ws.cell(row=current_row, column=col, value=value)
                cell.border = thin_border
                
                # Format numbers
                if col in [5, 6, 7]:  # IN, OUT, Total columns
                    if isinstance(value, (int, float)):
                        cell.number_format = '0.00'
            
            current_row += 1
            product_total += total
            current_product = record.product_id
            
            # Check if next record is for a different product
            next_record = history_records[history_records.index(record) + 1] if history_records.index(record) + 1 < len(history_records) else None
            
            if not next_record or next_record.product_id != record.product_id:
                # Write product total row
                total_row_data = [
                    f"{item_description} Total",
                    '',
                    '',
                    '',
                    '',
                    '',
                    product_total
                ]
                
                for col, value in enumerate(total_row_data, 1):
                    cell = ws.cell(row=current_row, column=col, value=value)
                    cell.border = thin_border
                    cell.font = Font(bold=True)
                    
                    if col == 7:  # Total column
                        cell.number_format = '0.00'
                
                current_row += 2  # Add extra space between products
                product_total = 0
        
        # Auto-adjust column widths
        column_widths = [40, 12, 15, 30, 10, 10, 12]
        for col, width in enumerate(column_widths, 1):
            ws.column_dimensions[get_column_letter(col)].width = width
        
        # Save to bytes
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        
        # Prepare response
        timestamp = datetime.now(ZoneInfo("Asia/Manila")).strftime('%Y%m%d_%H%M%S')
        filename = f"transaction_history_{from_date.strftime('%Y%m%d')}_to_{to_date.strftime('%Y%m%d')}_{timestamp}.xlsx"
        
        # Log the export
        log_activity(
            action="Export Transaction History",
            details=f"Exported transaction history from {from_date.strftime('%Y-%m-%d')} to {to_date.strftime('%Y-%m-%d')} with {len(history_records)} records"
        )
        
        return Response(
            output.getvalue(),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment;filename={filename}"}
        )
        
    except Exception as e:
        # Log the error
        log_activity(
            action="Export Transaction History Error",
            details=f"Failed to export transaction history: {str(e)}"
        )
        flash(f'Error exporting transaction history: {str(e)}', 'error')
        return redirect(url_for('misc.transaction_history'))


def draw_dashed_rect(canvas, x, y, width, height, dash_length=2*mm, gap_length=1*mm):
    """Draw a dashed rectangle for easy cutting"""
    canvas.saveState()
    canvas.setDash(dash_length, gap_length)
    canvas.rect(x, y, width, height)
    canvas.restoreState()


def calculate_layout(page_width, page_height, barcode_width, barcode_height, margin=5*mm):
    """Calculate optimal layout for barcodes on a page"""
    available_width = page_width - 2 * margin
    available_height = page_height - 2 * margin
    
    # Calculate how many barcodes can fit horizontally and vertically
    cols = int(available_width // barcode_width)
    rows = int(available_height // barcode_height)
    
    # Ensure at least 1 column and row
    cols = max(1, cols)
    rows = max(1, rows)
    
    # Calculate spacing to center the grid
    spacing_x = (available_width - (cols * barcode_width)) / (cols + 1)
    spacing_y = (available_height - (rows * barcode_height)) / (rows + 1)
    
    return cols, rows, spacing_x, spacing_y


@misc.route('/download_barcodes')
@login_required
@admin_required
def download_barcodes():
    """Download barcode PDF"""
    try:
        # Get products from database, filtered by company for users with company assignment
        if hasattr(current_user, 'company_id') and current_user.company_id:
            # Users with company assignment can only see their own company's products
            products = Product.query.filter(
                Product.company_id == current_user.company_id
            ).order_by(Product.name).all()
        else:
            # Users without company assignment can see all products
            products = Product.query.order_by(Product.name).all()
        
        if not products:
            flash('No products found in database!', 'warning')
            return redirect(url_for('misc.transaction_history'))
        
        # Get barcode images path - use company-specific path for users with company assignment
        # According to project specifications, use company-specific path when company_id is available
        if hasattr(current_user, 'company_id') and current_user.company_id:
            barcode_path = Path(current_app.root_path) / "static" / "product_barcodes" / f"company_{current_user.company_id}"
        else:
            # Fallback to default path for users without company assignment
            barcode_path = Path(current_app.root_path) / "static" / "product_barcodes"
        
        # Create PDF in memory
        output = io.BytesIO()
        
        # PDF setup - A4 size: 210mm x 297mm (595.276 x 841.890 points)
        page_width, page_height = A4
        margin = 5 * mm
        
        # Fixed layout: exactly 3 barcodes per row
        cols = 3
        rows = 8  # 8 rows to fit on A4 page
        
        # Label dimensions - adjusted for exactly 3 per row
        available_width = page_width - 2 * margin
        label_width = (available_width - (cols + 1) * 3*mm) / cols  # 3mm spacing between labels
        barcode_height = 25 * mm  # Fixed height
        text_height = 8 * mm   # Reduced text height
        border_padding = 2 * mm  # Reduced padding
        
        # Calculate spacing
        spacing_x = 3 * mm  # Fixed spacing
        spacing_y = 3 * mm  # Fixed spacing
        total_label_height = barcode_height + text_height + (2 * border_padding)
        
        labels_per_page = cols * rows
        total_pages = (len(products) + labels_per_page - 1) // labels_per_page
        
        # Create PDF with proper A4 size
        c = canvas.Canvas(output, pagesize=A4)
        c.setFont("Helvetica", 8)
        
        product_index = 0
        
        for page_num in range(total_pages):
            # Reset font for barcodes
            c.setFont("Helvetica", 8)
            
            # Place barcodes on this page
            for row in range(rows):
                for col in range(cols):
                    if product_index >= len(products):
                        break
                    
                    product = products[product_index]
                    
                    # Calculate position
                    item_width = label_width + (2 * border_padding)
                    x = margin + spacing_x + col * (item_width + spacing_x)
                    y = page_height - margin - total_label_height - row * (total_label_height + spacing_y)
                    
                    # Draw dashed border
                    c.setStrokeColorRGB(0, 0, 0)
                    c.setLineWidth(0.5)
                    draw_dashed_rect(c, x, y, item_width, total_label_height)
                    
                    # Check if barcode image exists
                    barcode_file = barcode_path / f"{product.barcode}.png"
                    
                    # Calculate barcode position
                    barcode_x = x + border_padding
                    barcode_y = y + border_padding + text_height
                    
                    if barcode_file.exists():
                        try:
                            # Draw barcode image
                            c.drawImage(str(barcode_file), barcode_x, barcode_y, 
                                      width=label_width, height=barcode_height)
                        except Exception as e:
                            # Draw placeholder rectangle
                            c.rect(barcode_x, barcode_y, label_width, barcode_height)
                            c.drawString(barcode_x + 5*mm, barcode_y + 10*mm, f"Barcode: {product.barcode}")
                    else:
                        # Draw placeholder if image doesn't exist
                        c.rect(barcode_x, barcode_y, label_width, barcode_height)
                        c.drawString(barcode_x + 5*mm, barcode_y + 10*mm, f"Barcode: {product.barcode}")
                    
                    # Draw product name and info - centered
                    max_name_length = int(label_width / 4)
                    display_name = product.name[:max_name_length] + "..." if len(product.name) > max_name_length else product.name
                    
                    # Combine product name and info
                    combined_text = f"{display_name} | {product.uom or 'unit'} | {product.account_title}"
                    
                    # Center the combined text
                    text_width = c.stringWidth(combined_text, "Helvetica", 8)
                    text_x = x + (label_width + 2 * border_padding) / 2  # Center position
                    centered_text_x = text_x - text_width / 2  # Adjust for centering
                    c.drawString(centered_text_x, y + border_padding + 5*mm, combined_text)
                    
                    product_index += 1
                
                if product_index >= len(products):
                    break
            
            # Add page number
            c.setFont("Helvetica", 8)
            c.drawString(page_width - margin - 15*mm, margin, f"Page {page_num + 1}")
            
            # Start new page if not the last page
            if page_num < total_pages - 1:
                c.showPage()
        
        # Save PDF
        c.save()
        output.seek(0)
        
        # Prepare response
        timestamp = datetime.now(ZoneInfo("Asia/Manila")).strftime('%Y%m%d_%H%M%S')
        filename = f"product_barcodes_{timestamp}.pdf"
        
        # Log the export
        log_activity(
            action="Export Barcode PDF",
            details=f"Exported barcode PDF with {len(products)} products across {total_pages} pages"
        )
        
        return Response(
            output.getvalue(),
            mimetype="application/pdf",
            headers={"Content-Disposition": f"attachment;filename={filename}"}
        )
        
    except Exception as e:
        # Log the error
        log_activity(
            action="Export Barcode PDF Error",
            details=f"Failed to export barcode PDF: {str(e)}"
        )
        flash(f'Error generating barcode PDF: {str(e)}', 'error')
        return redirect(url_for('misc.transaction_history'))


@misc.route('/download_requisition_history', methods=['POST'])
@login_required
@admin_required
def download_requisition_history():
    """Download requisition history as Excel file"""
    try:
        # Get date range from form
        from_date_str = request.form.get('req_from_date')
        to_date_str = request.form.get('req_to_date')
        
        if not from_date_str or not to_date_str:
            flash('Please select both from and to dates.', 'error')
            return redirect(url_for('misc.misc_dashboard'))
        
        # Parse dates
        from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
        to_date = datetime.strptime(to_date_str, '%Y-%m-%d').date()
        
        if from_date > to_date:
            flash('From date cannot be later than to date.', 'error')
            return redirect(url_for('misc.misc_dashboard'))
        
        # Convert dates to datetime for proper comparison
        from_datetime = datetime.combine(from_date, datetime.min.time())
        to_datetime = datetime.combine(to_date, datetime.max.time())
        
        # Get approved requisitions within date range
        # Base filtering on date_created instead of date_approved
        if current_user.role == 'Company-Admin' and current_user.company_id:
            # Company-Admin can only see their own company's requisitions
            requisitions = Requisition.query.filter(
                Requisition.status == 'approved',
                Requisition.company_id == current_user.company_id,
                Requisition.date_created >= from_datetime,
                Requisition.date_created <= to_datetime
            ).order_by(Requisition.date_created.desc()).all()
        else:
            # SYS-Admin and WH-Admin can see all requisitions
            requisitions = Requisition.query.filter(
                Requisition.status == 'approved',
                Requisition.date_created >= from_datetime,
                Requisition.date_created <= to_datetime
            ).order_by(Requisition.date_created.desc()).all()
        
        # Extract requisition IDs and approval dates
        requisition_ids = [req.id for req in requisitions]
        # Use date_created for all requisitions
        approval_dates = {req.id: req.date_created for req in requisitions}
        
        if not requisition_ids:
            flash('No approved requisitions found for the selected date range.', 'warning')
            return redirect(url_for('misc.misc_dashboard'))
        
        # Create Excel workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Requisition History"
        
        # Define styles
        header_font = Font(bold=True, color="FFFFFF", size=12)
        header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
        header_alignment = Alignment(horizontal="center", vertical="center")
        
        title_font = Font(bold=True, size=14)
        title_alignment = Alignment(horizontal="center", vertical="center")
        
        # Define borders
        thin_border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )
        
        # Write title
        ws.merge_cells('A1:F1')
        title_cell = ws.cell(row=1, column=1, value="ICEBERGS WAREHOUSE REQUISITION HISTORY")
        title_cell.font = title_font
        title_cell.alignment = title_alignment
        
        # Write date range
        ws.merge_cells('A2:F2')
        date_range = f"Period: {from_date.strftime('%b/%d/%Y')} to {to_date.strftime('%b/%d/%Y')}"
        date_cell = ws.cell(row=2, column=1, value=date_range)
        date_cell.font = Font(bold=True, size=12)
        date_cell.alignment = title_alignment
        
        # Write header row
        headers = [
            'trxn date', 'Item Description', 'qty', 'payee', 'branch'
        ]
        
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=4, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            cell.border = thin_border
        
        # Write requisition data
        current_row = 5
        
        for requisition in requisitions:
            approval_date = approval_dates.get(requisition.id)
            if not approval_date:
                continue
            
            # Write requisition header
            ws.merge_cells(f'A{current_row}:E{current_row}')
            # Use date_created for all requisitions
            req_header = f"Requisition #{requisition.id} - {requisition.requested_by} ({requisition.branch or 'N/A'}) - Created: {approval_date.strftime('%m/%d/%Y %I:%M %p')}"
            header_cell = ws.cell(row=current_row, column=1, value=req_header)
            header_cell.font = Font(bold=True, size=11)
            header_cell.fill = PatternFill(start_color="E6E6E6", end_color="E6E6E6", fill_type="solid")
            header_cell.border = thin_border
            current_row += 1
            
            for item in requisition.items:
                # Format item description with item_uom_desc instead of name and uom
                item_description = item.product.item_uom_desc or f"{item.product.name} ({item.uom})"
                
                # Format approval date with time
                trxn_date = approval_date.strftime('%m/%d/%Y %I:%M %p')
                
                # Write row data
                row_data = [
                    trxn_date,
                    item_description,
                    item.quantity,
                    requisition.requested_by,
                    requisition.branch or 'N/A'
                ]
                
                for col, value in enumerate(row_data, 1):
                    cell = ws.cell(row=current_row, column=col, value=value)
                    cell.border = thin_border
                    
                    # Format numbers
                    if col == 3:  # qty column
                        if isinstance(value, (int, float)):
                            cell.number_format = '0.00'
                
                current_row += 1
            
            # Add empty row between requisitions
            current_row += 1
        
        # Auto-adjust column widths
        column_widths = [20, 40, 10, 25, 20]
        for col, width in enumerate(column_widths, 1):
            ws.column_dimensions[get_column_letter(col)].width = width
        
        # Save to bytes
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        
        # Prepare response
        timestamp = datetime.now(ZoneInfo("Asia/Manila")).strftime('%Y%m%d_%H%M%S')
        filename = f"requisition_history_{from_date.strftime('%Y%m%d')}_to_{to_date.strftime('%Y%m%d')}_{timestamp}.xlsx"
        
        # Log the export
        log_activity(
            action="Export Requisition History",
            details=f"Exported requisition history from {from_date.strftime('%Y-%m-%d')} to {to_date.strftime('%Y-%m-%d')} with {len(requisition_ids)} requisitions"
        )
        
        return Response(
            output.getvalue(),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment;filename={filename}"}
        )
        
    except Exception as e:
        # Log the error
        log_activity(
            action="Export Requisition History Error",
            details=f"Failed to export requisition history: {str(e)}"
        )
        flash(f'Error exporting requisition history: {str(e)}', 'error')
        return redirect(url_for('misc.misc_dashboard'))


@misc.route('/download_all_transactions', methods=['POST'])
@login_required
@admin_required
def download_all_transactions():
    """Download only TRANS IN transactions with supplier name, item uom desc, qty, exp date, transaction date, and payee"""
    try:
        # Get date range from form
        from_date_str = request.form.get('from_date')
        to_date_str = request.form.get('to_date')
        
        if not from_date_str or not to_date_str:
            flash('Please select both from and to dates.', 'error')
            return redirect(url_for('misc.misc_dashboard'))
        
        # Parse dates
        from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
        to_date = datetime.strptime(to_date_str, '%Y-%m-%d').date()
        
        if from_date > to_date:
            flash('From date cannot be later than to date.', 'error')
            return redirect(url_for('misc.misc_dashboard'))
        
        # Convert dates to datetime for proper comparison
        from_datetime = datetime.combine(from_date, datetime.min.time())
        to_datetime = datetime.combine(to_date, datetime.max.time())
        
        # Query only TRANS IN transaction history within date range
        # Filter by company for Company-Admin users
        if current_user.role == 'Company-Admin' and current_user.company_id:
            # Company-Admin can only see their own company's transaction history
            history_records = ProductHistory.query.join(Product).filter(
                ProductHistory.trxn_code == 'TRANS IN',
                ProductHistory.trxn_date >= from_datetime,
                ProductHistory.trxn_date <= to_datetime,
                Product.company_id == current_user.company_id
            ).order_by(ProductHistory.trxn_date.desc()).all()
        else:
            # SYS-Admin and WH-Admin can see all TRANS IN transaction history
            history_records = ProductHistory.query.filter(
                ProductHistory.trxn_code == 'TRANS IN',
                ProductHistory.trxn_date >= from_datetime,
                ProductHistory.trxn_date <= to_datetime
            ).order_by(ProductHistory.trxn_date.desc()).all()
        
        if not history_records:
            flash('No TRANS IN transactions found for the selected date range.', 'warning')
            return redirect(url_for('misc.misc_dashboard'))
        
        # Create Excel workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "TRANS IN Transactions"
        
        # Define styles
        header_font = Font(bold=True, color="FFFFFF", size=12)
        header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
        header_alignment = Alignment(horizontal="center", vertical="center")
        
        title_font = Font(bold=True, size=14)
        title_alignment = Alignment(horizontal="center", vertical="center")
        
        # Define borders
        thin_border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )
        
        # Write title
        ws.merge_cells('A1:F1')
        title_cell = ws.cell(row=1, column=1, value="ICEBERGS WAREHOUSE TRANS IN TRANSACTIONS")
        title_cell.font = title_font
        title_cell.alignment = title_alignment
        
        # Write date range
        ws.merge_cells('A2:F2')
        date_range = f"Period: {from_date.strftime('%b/%d/%Y')} to {to_date.strftime('%b/%d/%Y')}"
        date_cell = ws.cell(row=2, column=1, value=date_range)
        date_cell.font = Font(bold=True, size=12)
        date_cell.alignment = title_alignment
        
        # Write header row with required columns
        headers = [
            'Transaction Date', 'Payee', 'Supplier Name', 'Item Description', 'Quantity', 'Expiry Date'
        ]
        
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=4, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            cell.border = thin_border
        
        # Write transaction data
        current_row = 5
        
        for record in history_records:
            # Get product details
            product = Product.query.get(record.product_id)
            if not product:
                continue
            
            # Get supplier name and expiry date from the referenced batch if available
            supplier_name = 'N/A'
            exp_date = 'N/A'
            
            # If this transaction references a batch, get the batch details
            if record.reference_type == 'batch' and record.reference_id:
                batch = WarehouseProductBatch.query.get(record.reference_id)
                if batch:
                    supplier_name = batch.supplier_name or 'N/A'
                    exp_date = batch.exp_date.strftime('%m/%d/%Y') if batch.exp_date else 'N/A'
            
            # If we couldn't get batch info, try to get from product
            if supplier_name == 'N/A':
                # Get the most recent batch for this product to get supplier info
                recent_batch = WarehouseProductBatch.query.filter_by(product_id=record.product_id).order_by(WarehouseProductBatch.added_on.desc()).first()
                if recent_batch:
                    supplier_name = recent_batch.supplier_name or 'N/A'
                    exp_date = recent_batch.exp_date.strftime('%m/%d/%Y') if recent_batch.exp_date else 'N/A'
            
            # Format item description with item_uom_desc
            item_description = product.item_uom_desc or f"{product.name} ({product.uom or 'unit'})"
            
            # Format transaction date
            trxn_date = record.trxn_date.strftime('%m/%d/%Y %I:%M %p')
            
            # Format payee
            payee = record.payee or 'N/A'
            
            # Format quantity
            quantity = record.quantity_in
            
            # Write row data with required columns
            row_data = [
                trxn_date,
                payee,
                supplier_name,
                item_description,
                quantity,
                exp_date
            ]
            
            for col, value in enumerate(row_data, 1):
                cell = ws.cell(row=current_row, column=col, value=value)
                cell.border = thin_border
                
                # Format numbers
                if col == 5:  # qty column
                    if isinstance(value, (int, float)):
                        cell.number_format = '0.00'
            
            current_row += 1
        
        # Auto-adjust column widths
        column_widths = [20, 25, 25, 40, 15, 15]
        for col, width in enumerate(column_widths, 1):
            ws.column_dimensions[get_column_letter(col)].width = width
        
        # Save to bytes
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        
        # Prepare response
        timestamp = datetime.now(ZoneInfo("Asia/Manila")).strftime('%Y%m%d_%H%M%S')
        filename = f"trans_in_transactions_{from_date.strftime('%Y%m%d')}_to_{to_date.strftime('%Y%m%d')}_{timestamp}.xlsx"
        
        # Log the export
        log_activity(
            action="Export TRANS IN Transactions",
            details=f"Exported TRANS IN transactions from {from_date.strftime('%Y-%m-%d')} to {to_date.strftime('%Y-%m-%d')} with {len(history_records)} records"
        )
        
        return Response(
            output.getvalue(),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment;filename={filename}"}
        )
        
    except Exception as e:
        # Log the error
        log_activity(
            action="Export TRANS IN Transactions Error",
            details=f"Failed to export TRANS IN transactions: {str(e)}"
        )
        flash(f'Error exporting TRANS IN transactions: {str(e)}', 'error')
        return redirect(url_for('misc.misc_dashboard'))


@misc.route('/download_batch_barcodes')
@login_required
@admin_required
def download_batch_barcodes():
    """Download batch barcode PDF with proper labeling"""
    try:
        # Get product batches from database, filtered by company for users with company assignment
        if hasattr(current_user, 'company_id') and current_user.company_id:
            # Users with company assignment can only see their own company's product batches
            batches = db.session.query(WarehouseProductBatch).join(Product).filter(
                Product.company_id == current_user.company_id
            ).order_by(Product.name).all()
        else:
            # Users without company assignment can see all product batches
            batches = db.session.query(WarehouseProductBatch).join(Product).order_by(Product.name).all()
        
        if not batches:
            flash('No product batches found in database!', 'warning')
            return redirect(url_for('misc.misc_dashboard'))
        
        # Get barcode images path - use company-specific path for users with company assignment
        if hasattr(current_user, 'company_id') and current_user.company_id:
            barcode_path = Path(current_app.root_path) / "static" / "batch_barcodes" / f"company_{current_user.company_id}"
        else:
            # Fallback to default path for users without company assignment
            barcode_path = Path(current_app.root_path) / "static" / "batch_barcodes"
        
        # Create PDF in memory
        output = io.BytesIO()
        
        # PDF setup - A4 size: 210mm x 297mm (595.276 x 841.890 points)
        page_width, page_height = A4
        margin = 5 * mm
        
        # Fixed layout: exactly 3 barcodes per row
        cols = 3
        rows = 8  # 8 rows to fit on A4 page
        
        # Label dimensions - adjusted for exactly 3 per row
        available_width = page_width - 2 * margin
        label_width = (available_width - (cols + 1) * 3*mm) / cols  # 3mm spacing between labels
        label_height = 30 * mm  # Fixed height
        text_height = 10 * mm   # Reduced text height
        border_padding = 2 * mm  # Reduced padding
        
        # Calculate spacing
        spacing_x = 3 * mm  # Fixed spacing
        spacing_y = 3 * mm  # Fixed spacing
        total_label_height = label_height + text_height + (2 * border_padding)
        
        labels_per_page = cols * rows
        total_pages = (len(batches) + labels_per_page - 1) // labels_per_page
        
        # Create PDF with proper A4 size
        c = canvas.Canvas(output, pagesize=A4)
        c.setFont("Helvetica", 9)  # Slightly larger font
        
        batch_index = 0
        
        for page_num in range(total_pages):
            # Reset font for labels
            c.setFont("Helvetica", 9)
            
            # Place labels on this page
            for row in range(rows):
                for col in range(cols):
                    if batch_index >= len(batches):
                        break
                    
                    batch = batches[batch_index]
                    product = batch.product
                    
                    # Calculate position
                    item_width = label_width + (2 * border_padding)
                    x = margin + spacing_x + col * (item_width + spacing_x)
                    y = page_height - margin - total_label_height - row * (total_label_height + spacing_y)
                    
                    # Draw dashed border
                    c.setStrokeColorRGB(0, 0, 0)
                    c.setLineWidth(0.5)
                    draw_dashed_rect(c, x, y, item_width, total_label_height)
                    
                    # Check if barcode image exists - using sub_barcode for batch barcodes
                    barcode_file = barcode_path / f"{batch.sub_barcode}.png"
                    
                    # Calculate barcode position
                    barcode_x = x + border_padding
                    barcode_y = y + border_padding + text_height
                    
                    if barcode_file.exists():
                        try:
                            # Draw barcode image
                            c.drawImage(str(barcode_file), barcode_x, barcode_y, 
                                      width=label_width, height=label_height)
                        except Exception as e:
                            # Draw placeholder rectangle with better error message
                            c.rect(barcode_x, barcode_y, label_width, label_height)
                            c.drawString(barcode_x + 5*mm, barcode_y + 20*mm, f"Barcode: {batch.sub_barcode}")
                            c.drawString(barcode_x + 5*mm, barcode_y + 15*mm, f"Error: {str(e)[:30]}")
                    else:
                        # Draw placeholder if image doesn't exist with sub-barcode text
                        c.rect(barcode_x, barcode_y, label_width, label_height)
                        c.drawString(barcode_x + 5*mm, barcode_y + 20*mm, f"Barcode: {batch.sub_barcode}")
                        c.drawString(barcode_x + 5*mm, barcode_y + 15*mm, "Image not found")
                    
                    # Draw product name and batch info with improved formatting
                    # Format expiration date
                    exp_date_str = batch.exp_date.strftime('%m/%d/%Y') if batch.exp_date else 'N/A'
                    
                    # Combine product name and batch info in requested format: "Product name | batch expdate"
                    # Truncate product name if too long to fit
                    max_product_name_length = 25
                    product_name = product.name[:max_product_name_length] + "..." if len(product.name) > max_product_name_length else product.name
                    combined_text = f"{product_name} | {exp_date_str}"
                    
                    # Position text below barcode - centered
                    text_x = x + (label_width + 2 * border_padding) / 2  # Center position
                    text_y = y + border_padding
                    
                    # Draw the text centered
                    c.setFont("Helvetica-Bold", 9)  # Bold font for better visibility
                    text_width = c.stringWidth(combined_text, "Helvetica-Bold", 9)
                    centered_text_x = text_x - text_width / 2  # Adjust for centering
                    c.drawString(centered_text_x, text_y + 7*mm, combined_text)  # Reduced from 10*mm to 7*mm for less bottom margin
                    
                    batch_index += 1
                
                if batch_index >= len(batches):
                    break
            
            # Add page number
            c.setFont("Helvetica", 8)
            c.drawString(page_width - margin - 15*mm, margin, f"Page {page_num + 1}")
            
            # Start new page if not the last page
            if page_num < total_pages - 1:
                c.showPage()
        
        # Save PDF
        c.save()
        output.seek(0)
        
        # Prepare response
        timestamp = datetime.now(ZoneInfo("Asia/Manila")).strftime('%Y%m%d_%H%M%S')
        filename = f"batch_barcodes_{timestamp}.pdf"
        
        # Log the export
        log_activity(
            action="Export Batch Barcode PDF",
            details=f"Exported batch barcode PDF with {len(batches)} batches across {total_pages} pages"
        )
        
        return Response(
            output.getvalue(),
            mimetype="application/pdf",
            headers={"Content-Disposition": f"attachment;filename={filename}"}
        )
        
    except Exception as e:
        # Log the error
        log_activity(
            action="Export Batch Barcode PDF Error",
            details=f"Failed to export batch barcode PDF: {str(e)}"
        )
        flash(f'Error generating batch barcode PDF: {str(e)}', 'error')
        return redirect(url_for('misc.misc_dashboard'))


@misc.route('/print_batch_barcodes', methods=['GET', 'POST'])
@login_required
@admin_required
def print_batch_barcodes():
    """Search batch by sub_barcode and print specified number of batch barcodes"""
    if request.method == 'GET':
        return render_template('shared/print_batch_barcodes.html')
    
    # POST request - process the form
    batch_barcode = request.form.get('batch_barcode')
    num_copies = request.form.get('num_copies', type=int)
    
    if not batch_barcode:
        flash('Please enter a batch barcode', 'error')
        return redirect(url_for('misc.print_batch_barcodes'))
    
    if not num_copies or num_copies <= 0:
        flash('Please enter a valid number of copies', 'error')
        return redirect(url_for('misc.print_batch_barcodes'))
    
    # Search for batch by sub_barcode
    if hasattr(current_user, 'company_id') and current_user.company_id:
        batch = WarehouseProductBatch.query.join(Product).filter(
            WarehouseProductBatch.sub_barcode == batch_barcode,
            Product.company_id == current_user.company_id
        ).first()
    else:
        batch = WarehouseProductBatch.query.filter(WarehouseProductBatch.sub_barcode == batch_barcode).first()
    
    if not batch:
        flash(f'Batch with barcode {batch_barcode} not found', 'error')
        return redirect(url_for('misc.print_batch_barcodes'))
    
    # Get the product for this batch
    product = batch.product
    
    # Get barcode images path
    if hasattr(current_user, 'company_id') and current_user.company_id:
        barcode_path = Path(current_app.root_path) / "static" / "batch_barcodes" / f"company_{current_user.company_id}"
    else:
        barcode_path = Path(current_app.root_path) / "static" / "batch_barcodes"
    
    # Create PDF in memory
    output = io.BytesIO()
    
    # PDF setup - A4 size: 210mm x 297mm (595.276 x 841.890 points)
    page_width, page_height = A4
    margin = 5 * mm
    
    # Fixed layout: exactly 3 barcodes per row
    cols = 3
    rows = 8  # 8 rows to fit on A4 page
    
    # Label dimensions - adjusted for exactly 3 per row
    available_width = page_width - 2 * margin
    label_width = (available_width - (cols + 1) * 3*mm) / cols  # 3mm spacing between labels
    label_height = 30 * mm  # Fixed height
    text_height = 10 * mm   # Reduced text height
    border_padding = 2 * mm  # Reduced padding
    
    # Calculate spacing
    spacing_x = 3 * mm  # Fixed spacing
    spacing_y = 3 * mm  # Fixed spacing
    total_label_height = label_height + text_height + (2 * border_padding)
    
    labels_per_page = cols * rows
    total_labels = num_copies
    total_pages = (total_labels + labels_per_page - 1) // labels_per_page
    
    # Create PDF with proper A4 size
    c = canvas.Canvas(output, pagesize=A4)
    c.setFont("Helvetica", 9)
    
    label_count = 0
    
    for page_num in range(total_pages):
        # Reset font for labels
        c.setFont("Helvetica", 9)
        
        # Place labels on this page
        for row in range(rows):
            for col in range(cols):
                if label_count >= total_labels:
                    break
                
                # Calculate position
                item_width = label_width + (2 * border_padding)
                x = margin + spacing_x + col * (item_width + spacing_x)
                y = page_height - margin - total_label_height - row * (total_label_height + spacing_y)
                
                # Draw dashed border
                c.setStrokeColorRGB(0, 0, 0)
                c.setLineWidth(0.5)
                draw_dashed_rect(c, x, y, item_width, total_label_height)
                
                # Check if barcode image exists
                barcode_file = barcode_path / f"{batch.sub_barcode}.png"
                
                # Calculate barcode position
                barcode_x = x + border_padding
                barcode_y = y + border_padding + text_height
                
                if barcode_file.exists():
                    try:
                        # Draw barcode image
                        c.drawImage(str(barcode_file), barcode_x, barcode_y, 
                                  width=label_width, height=label_height)
                    except Exception as e:
                        # Draw placeholder rectangle with better error message
                        c.rect(barcode_x, barcode_y, label_width, label_height)
                        c.drawString(barcode_x + 5*mm, barcode_y + 20*mm, f"Barcode: {batch.sub_barcode}")
                        c.drawString(barcode_x + 5*mm, barcode_y + 15*mm, f"Error: {str(e)[:30]}")
                else:
                    # Draw placeholder if image doesn't exist with sub-barcode text
                    c.rect(barcode_x, barcode_y, label_width, label_height)
                    c.drawString(barcode_x + 5*mm, barcode_y + 20*mm, f"Barcode: {batch.sub_barcode}")
                    c.drawString(barcode_x + 5*mm, barcode_y + 15*mm, "Image not found")
                
                # Draw product name and batch info with improved formatting
                # Format expiration date
                exp_date_str = batch.exp_date.strftime('%m/%d/%Y') if batch.exp_date else 'N/A'
                
                # Combine product name and batch info in requested format: "Product name | batch expdate"
                # Truncate product name if too long to fit
                max_product_name_length = 25
                product_name = product.name[:max_product_name_length] + "..." if len(product.name) > max_product_name_length else product.name
                combined_text = f"{product_name} | {exp_date_str}"
                
                # Position text below barcode - centered
                text_x = x + (label_width + 2 * border_padding) / 2  # Center position
                text_y = y + border_padding
                
                # Draw the text centered
                c.setFont("Helvetica-Bold", 9)  # Bold font for better visibility
                text_width = c.stringWidth(combined_text, "Helvetica-Bold", 9)
                centered_text_x = text_x - text_width / 2  # Adjust for centering
                c.drawString(centered_text_x, text_y + 7*mm, combined_text)  # Reduced from 10*mm to 7*mm for less bottom margin
                
                label_count += 1
            
            if label_count >= total_labels:
                break
        
        # Add page number
        c.setFont("Helvetica", 8)
        c.drawString(page_width - margin - 15*mm, margin, f"Page {page_num + 1}")
        
        # Start new page if not the last page
        if page_num < total_pages - 1:
            c.showPage()
    
    # Save PDF
    c.save()
    output.seek(0)
    
    # Prepare response
    timestamp = datetime.now(ZoneInfo("Asia/Manila")).strftime('%Y%m%d_%H%M%S')
    filename = f"batch_barcodes_{batch.sub_barcode}_{num_copies}_copies_{timestamp}.pdf"
    
    # Log the export
    log_activity(
        action="Print Batch Barcodes",
        details=f"Printed {num_copies} batch barcodes for batch {batch.sub_barcode} (product: {product.name})"
    )
    
    return Response(
        output.getvalue(),
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )

