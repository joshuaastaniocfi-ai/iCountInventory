# Standard library imports
import io
from datetime import datetime
from zoneinfo import ZoneInfo

# Third-party imports
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_login import login_required, current_user
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

# Local imports
from extensions import db
from models import RawItem, Requisition

raw_items_bp = Blueprint('raw_items', __name__, url_prefix='/user/raw-items')

SAMPLE_HEADERS = [
    'Raw Material',
    'Qty/Rtl',
    'UOM',
    'Measurement/Order',
    'UOM2'
]

# Sample raw material rows from PRODUCT ICEBERGS (1).xlsx
SAMPLE_ROWS = [
    ['Ice cream Ube royale (1x3L=32scoops)', 28, 'Piece', 1, 'Piece'],
    ['Ice cream Strawberry (1x3L=32scoops)', 28, 'Piece', 1, 'Piece'],
    ['Ice cream Mango (1x3L=32scoops)', 28, 'Piece', 1, 'Piece'],
    ['Ice cream Vanilla (1x3L=32scoops)', 28, 'Piece', 1, 'Piece'],
    ['Ripe mango (1kl=1000grams)', 1000, 'Grams', 50, 'Grams'],
    ['Macapuno balls (1btl=122pcs)', 122, 'Piece', 4, 'Piece'],
    ['Banana lakatan (1kl=1000grams)', 1000, 'Piece', 130, 'Piece'],
    ['Pineapple Sliced (1can=836grams@16slices)', 8, 'Piece', 1, 'Piece'],
    ['Strawberry Syrup (1gal=3785grams)', 3785, 'Piece', 100, 'Piece'],
    ['Whipping Cream (1pack=1000grams)', 1000, 'Piece', 100, 'Piece'],
    ['Cherry w/ stem (1btl=1kgrams/76pcs)', 76, 'Piece', 1, 'Piece'],
    ['almonds slice (1pack=1000grams)', 1000, 'Piece', 50, 'Piece'],
    ['assorted sprinkles (1pack=1000grams)', 1000, 'Piece', 10, 'Piece'],
]


def _can_access_raw_items():
    return current_user.is_authenticated and current_user.role in ('User', 'SYS-Admin')


def _scoped_query():
    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        return RawItem.query
    return RawItem.query.filter_by(company_id=current_user.company_id)


def _to_float(val, default=0.0):
    if val is None or str(val).strip() == '':
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _normalize_header(text):
    return str(text or '').strip().lower().replace('_', ' ')


def _build_column_map(header_row):
    """Map expected column keys to 0-based indices from an Excel header row."""
    aliases = {
        'raw_material': {'raw material', 'raw_material', 'raw materials', 'material', 'ingredient'},
        'qty_rtl': {'qty/rtl', 'qty rtl', 'qty_rtl', 'qty', 'quantity'},
        'uom': {'uom', 'unit'},
        'measurement_order': {'measurement/order', 'measurement order', 'measurement_order', 'measurement', 'order qty'},
        'uom2': {'uom2', 'uom 2', 'order uom', 'unit 2'},
    }
    col_map = {}
    for idx, cell in enumerate(header_row):
        norm = _normalize_header(cell)
        for field, names in aliases.items():
            if norm in names and field not in col_map:
                col_map[field] = idx
                break
    return col_map


@raw_items_bp.route('', methods=['GET'])
@login_required
def index():
    """Render the dedicated full-screen Raw Items management page for the User role."""
    if not _can_access_raw_items():
        flash('Access denied. This page is for User role raw inventory management.', 'error')
        return redirect(url_for('main.dashboard'))

    items = _scoped_query().order_by(RawItem.id.desc()).all()
    items_data = [item.to_dict() for item in items]

    pending_receiving_count = Requisition.query.filter(
        (Requisition.company_id == current_user.company_id) |
        (Requisition.destination_company_id == current_user.company_id),
        Requisition.status.in_(['Dispatched', 'dispatched', 'Partial', 'partial'])
    ).count() if current_user.company_id else 0

    return render_template(
        'user/raw_items.html',
        raw_items_data=items_data,
        pending_receiving_count=pending_receiving_count,
    )


@raw_items_bp.route('/list', methods=['GET'])
@login_required
def list_items():
    """Return all raw items for the current company as JSON."""
    if not _can_access_raw_items():
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    items = _scoped_query().order_by(RawItem.id.desc()).all()
    return jsonify({
        'success': True,
        'items': [item.to_dict() for item in items],
        'total': len(items)
    })


@raw_items_bp.route('/add', methods=['POST'])
@login_required
def add_item():
    """Manually add a single raw item row into inventory_db.raw_items."""
    if not _can_access_raw_items():
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    data = request.get_json(silent=True) or request.form

    raw_material = (data.get('raw_material') or '').strip()
    uom = (data.get('uom') or '').strip()
    uom2 = (data.get('uom2') or '').strip()
    qty_rtl = _to_float(data.get('qty_rtl'), 0.0)
    measurement_order = _to_float(data.get('measurement_order'), 0.0)

    if not raw_material:
        return jsonify({
            'success': False,
            'message': 'Raw Material is required.'
        }), 400

    existing = _scoped_query().filter(
        db.func.lower(db.func.trim(RawItem.raw_material)) == raw_material.lower()
    ).first()
    if existing:
        return jsonify({
            'success': False,
            'message': f'"{raw_material}" already exists.'
        }), 400

    item = RawItem(
        company_id=current_user.company_id,
        raw_material=raw_material,
        qty_rtl=qty_rtl,
        uom=uom,
        measurement_order=measurement_order,
        uom2=uom2,
        created_by=current_user.full_name,
    )
    db.session.add(item)
    db.session.commit()

    return jsonify({
        'success': True,
        'message': 'Raw item added successfully.',
        'item': item.to_dict()
    })


@raw_items_bp.route('/edit/<int:item_id>', methods=['POST'])
@login_required
def edit_item(item_id):
    """Update an existing raw item row in inventory_db.raw_items."""
    if not _can_access_raw_items():
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    item = _scoped_query().filter_by(id=item_id).first()
    if not item:
        return jsonify({'success': False, 'message': 'Raw item not found.'}), 404

    data = request.get_json(silent=True) or request.form
    raw_material = (data.get('raw_material') or '').strip()

    if not raw_material:
        return jsonify({
            'success': False,
            'message': 'Raw Material is required.'
        }), 400

    duplicate = _scoped_query().filter(
        RawItem.id != item_id,
        db.func.lower(db.func.trim(RawItem.raw_material)) == raw_material.lower()
    ).first()
    if duplicate:
        return jsonify({
            'success': False,
            'message': f'"{raw_material}" already exists.'
        }), 400

    item.raw_material = raw_material
    item.qty_rtl = _to_float(data.get('qty_rtl'), 0.0)
    item.uom = (data.get('uom') or '').strip()
    item.measurement_order = _to_float(data.get('measurement_order'), 0.0)
    item.uom2 = (data.get('uom2') or '').strip()
    item.updated_at = datetime.now(ZoneInfo("Asia/Manila"))

    db.session.commit()
    return jsonify({
        'success': True,
        'message': 'Raw item updated.',
        'item': item.to_dict()
    })


@raw_items_bp.route('/delete/<int:item_id>', methods=['POST'])
@login_required
def delete_item(item_id):
    """Delete a raw item row from inventory_db.raw_items."""
    if not _can_access_raw_items():
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    item = _scoped_query().filter_by(id=item_id).first()
    if not item:
        return jsonify({'success': False, 'message': 'Raw item not found.'}), 404

    db.session.delete(item)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Raw item deleted.'})


@raw_items_bp.route('/export', methods=['GET'])
@login_required
def export_excel():
    """Export raw_items table rows (optionally filtered by q and uom) to an Excel file."""
    if not _can_access_raw_items():
        flash('Access denied.', 'error')
        return redirect(url_for('main.dashboard'))

    q = (request.args.get('q') or '').strip().lower()
    uom = (request.args.get('uom') or '').strip()

    query = _scoped_query()
    if uom:
        query = query.filter(RawItem.uom == uom)

    items = query.order_by(RawItem.id.asc()).all()
    if q:
        items = [
            item for item in items
            if q in f"{item.raw_material or ''} {item.uom or ''} {item.uom2 or ''}".lower()
        ]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Raw Items'

    ws.append(SAMPLE_HEADERS)
    header_fill = PatternFill(start_color='18181B', end_color='18181B', fill_type='solid')
    header_font = Font(bold=True, color='FFFFFF')
    for col_idx in range(1, len(SAMPLE_HEADERS) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='left', vertical='center')

    for item in items:
        ws.append([
            item.raw_material or '',
            float(item.qty_rtl or 0),
            item.uom or '',
            float(item.measurement_order or 0),
            item.uom2 or '',
        ])

    widths = [42, 12, 12, 20, 12]
    for idx, width in enumerate(widths, start=1):
        col_letter = openpyxl.utils.get_column_letter(idx)
        ws.column_dimensions[col_letter].width = width

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name='raw_items_export.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


@raw_items_bp.route('/upload', methods=['POST'])
@login_required
def upload_excel():
    """Upload an Excel (.xlsx) file to bulk-import rows into inventory_db.raw_items."""
    if not _can_access_raw_items():
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'success': False, 'message': 'Please select an Excel (.xlsx) file to upload.'}), 400

    filename_lower = file.filename.lower()
    if not filename_lower.endswith(('.xlsx', '.xlsm')):
        return jsonify({'success': False, 'message': 'Only .xlsx or .xlsm Excel files are supported.'}), 400

    replace_existing = str(request.form.get('replace_existing', 'false')).lower() in ('true', '1', 'yes', 'on')

    try:
        wb = openpyxl.load_workbook(file, data_only=True, read_only=True)
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        header_row = next(rows_iter, None)
        if not header_row:
            return jsonify({'success': False, 'message': 'The uploaded Excel sheet is empty.'}), 400

        col_map = _build_column_map(header_row)
        if 'raw_material' not in col_map:
            return jsonify({
                'success': False,
                'message': (
                    'Missing required "Raw Material" column in Excel header. '
                    'Expected: Raw Material, Qty/Rtl, UOM, Measurement/Order, UOM2.'
                )
            }), 400

        existing_keys = set()
        if not replace_existing:
            existing_keys = {
                (r[0] or '').strip().lower()
                for r in _scoped_query().with_entities(RawItem.raw_material).all()
                if (r[0] or '').strip()
            }

        new_items = []
        skipped = 0
        duplicates = 0
        seen_in_upload = set()
        now_ph = datetime.now(ZoneInfo("Asia/Manila"))

        for row in rows_iter:
            def cell(field):
                idx = col_map.get(field)
                if idx is None or idx >= len(row):
                    return None
                return row[idx]

            raw_material = str(cell('raw_material') or '').strip()
            if not raw_material:
                skipped += 1
                continue

            raw_key = raw_material.lower()
            if raw_key in existing_keys or raw_key in seen_in_upload:
                duplicates += 1
                continue
            seen_in_upload.add(raw_key)

            new_items.append(RawItem(
                company_id=current_user.company_id,
                raw_material=raw_material,
                qty_rtl=_to_float(cell('qty_rtl'), 0.0),
                uom=str(cell('uom') or '').strip(),
                measurement_order=_to_float(cell('measurement_order'), 0.0),
                uom2=str(cell('uom2') or '').strip(),
                created_by=current_user.full_name,
                created_at=now_ph,
                updated_at=now_ph,
            ))

        wb.close()

        if not new_items:
            msg = (
                f'No new raw items imported ({duplicates} duplicate(s) skipped).'
                if duplicates else
                'No valid raw material rows were found in the Excel file.'
            )
            return jsonify({'success': False, 'message': msg}), 400

        if replace_existing:
            _scoped_query().delete(synchronize_session=False)

        db.session.bulk_save_objects(new_items)
        db.session.commit()

        details = []
        if duplicates:
            details.append(f'{duplicates} duplicate(s) skipped')
        if skipped:
            details.append(f'{skipped} blank row(s) skipped')
        suffix = f" ({', '.join(details)})." if details else '.'

        return jsonify({
            'success': True,
            'inserted': len(new_items),
            'duplicates': duplicates,
            'skipped': skipped,
            'message': f'Imported {len(new_items)} unique raw item(s){suffix}'
        })

    except Exception as exc:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Failed to process Excel file: {exc}'}), 400


@raw_items_bp.route('/download-sample', methods=['GET'])
@login_required
def download_sample():
    """Generate and download a sample Excel template using raw_material rows."""
    if not _can_access_raw_items():
        flash('Access denied.', 'error')
        return redirect(url_for('main.dashboard'))

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Raw Items'

    # Header row
    ws.append(SAMPLE_HEADERS)
    header_fill = PatternFill(start_color='18181B', end_color='18181B', fill_type='solid')
    header_font = Font(bold=True, color='FFFFFF')
    for col_idx in range(1, len(SAMPLE_HEADERS) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='left', vertical='center')

    for row in SAMPLE_ROWS:
        ws.append(row)

    widths = [42, 12, 12, 20, 12]
    for idx, width in enumerate(widths, start=1):
        col_letter = openpyxl.utils.get_column_letter(idx)
        ws.column_dimensions[col_letter].width = width

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name='raw_items_sample_icebergs.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
