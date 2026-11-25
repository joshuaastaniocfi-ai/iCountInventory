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
from models import RawItem, ProductRecipe, Requisition

product_recipes_bp = Blueprint('product_recipes', __name__, url_prefix='/user/product-recipes')

SAMPLE_HEADERS = ['Category', 'Product name', 'Raw Material', 'Measurement/Order', 'UOM2']

SAMPLE_ROWS = [
    ['Cool Seductions', 'DRIZZLE', 'Ice cream Ube royale (1x3L=32scoops)', 1, 'Piece'],
    ['Cool Seductions', 'DRIZZLE', 'Ice cream Strawberry (1x3L=32scoops)', 1, 'Piece'],
    ['Cool Seductions', 'DRIZZLE', 'Ripe mango (1kl=1000grams)', 50, 'Grams'],
    ['Cool Seductions', 'DRIZZLE', 'Macapuno balls (1btl=122pcs)', 4, 'Piece'],
    ['Cool Seductions', 'DRIZZLE', 'Whipping Cream (1pack=1000grams)', 100, 'Piece'],
]


def _can_access():
    return current_user.is_authenticated and current_user.role in ('User', 'SYS-Admin')


def _scoped_query():
    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        return ProductRecipe.query
    return ProductRecipe.query.filter_by(company_id=current_user.company_id)


def _raw_items_lookup():
    """Map lowercase raw_material name -> RawItem.id for linking."""
    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        items = RawItem.query.with_entities(RawItem.id, RawItem.raw_material).all()
    else:
        items = RawItem.query.filter_by(company_id=current_user.company_id).with_entities(
            RawItem.id, RawItem.raw_material
        ).all()
    return {(name or '').strip().lower(): rid for rid, name in items if (name or '').strip()}, [
        name for _, name in sorted(items, key=lambda x: (x[1] or '').lower()) if (name or '').strip()
    ]


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
    aliases = {
        'category': {'category', 'cat'},
        'product_name': {'product name', 'product_name', 'product'},
        'raw_material': {'raw material', 'raw_material', 'raw materials', 'material', 'ingredient'},
        'recipe_qty': {'measurement/order', 'measurement order', 'measurement_order', 'recipe qty', 'qty', 'measurement'},
        'recipe_uom': {'uom2', 'uom 2', 'recipe uom', 'order uom', 'uom'},
    }
    col_map = {}
    for idx, cell in enumerate(header_row):
        norm = _normalize_header(cell)
        for field, names in aliases.items():
            if norm in names and field not in col_map:
                col_map[field] = idx
                break
    return col_map


@product_recipes_bp.route('', methods=['GET'])
@login_required
def index():
    """Render the Product Recipes mapping page."""
    if not _can_access():
        flash('Access denied.', 'error')
        return redirect(url_for('main.dashboard'))

    recipes = _scoped_query().order_by(ProductRecipe.category.asc(), ProductRecipe.product_name.asc(), ProductRecipe.id.asc()).all()
    _, raw_names = _raw_items_lookup()

    pending_receiving_count = Requisition.query.filter(
        (Requisition.company_id == current_user.company_id) |
        (Requisition.destination_company_id == current_user.company_id),
        Requisition.status.in_(['Dispatched', 'dispatched', 'Partial', 'partial'])
    ).count() if current_user.company_id else 0

    return render_template(
        'user/product_recipes.html',
        recipes_data=[r.to_dict() for r in recipes],
        raw_material_names=raw_names,
        pending_receiving_count=pending_receiving_count,
    )


@product_recipes_bp.route('/list', methods=['GET'])
@login_required
def list_recipes():
    if not _can_access():
        return jsonify({'success': False, 'message': 'Access denied.'}), 403
    recipes = _scoped_query().order_by(ProductRecipe.category.asc(), ProductRecipe.product_name.asc(), ProductRecipe.id.asc()).all()
    return jsonify({'success': True, 'items': [r.to_dict() for r in recipes], 'total': len(recipes)})


@product_recipes_bp.route('/add', methods=['POST'])
@login_required
def add_recipe():
    if not _can_access():
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    data = request.get_json(silent=True) or request.form
    category = (data.get('category') or '').strip()
    product_name = (data.get('product_name') or '').strip()
    raw_material = (data.get('raw_material') or '').strip()
    recipe_qty = _to_float(data.get('recipe_qty'), 0.0)
    recipe_uom = (data.get('recipe_uom') or '').strip()

    if not category or not product_name or not raw_material:
        return jsonify({'success': False, 'message': 'Category, Product Name, and Raw Material are required.'}), 400

    dup = _scoped_query().filter(
        db.func.lower(db.func.trim(ProductRecipe.category)) == category.lower(),
        db.func.lower(db.func.trim(ProductRecipe.product_name)) == product_name.lower(),
        db.func.lower(db.func.trim(ProductRecipe.raw_material)) == raw_material.lower(),
    ).first()
    if dup:
        return jsonify({'success': False, 'message': f'"{raw_material}" is already mapped to "{product_name}".'}), 400

    raw_map, _ = _raw_items_lookup()
    item = ProductRecipe(
        company_id=current_user.company_id,
        category=category,
        product_name=product_name,
        raw_item_id=raw_map.get(raw_material.lower()),
        raw_material=raw_material,
        recipe_qty=recipe_qty,
        recipe_uom=recipe_uom,
        created_by=current_user.full_name,
    )
    db.session.add(item)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Recipe item added.', 'item': item.to_dict()})


@product_recipes_bp.route('/edit/<int:item_id>', methods=['POST'])
@login_required
def edit_recipe(item_id):
    if not _can_access():
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    item = _scoped_query().filter_by(id=item_id).first()
    if not item:
        return jsonify({'success': False, 'message': 'Recipe item not found.'}), 404

    data = request.get_json(silent=True) or request.form
    category = (data.get('category') or '').strip()
    product_name = (data.get('product_name') or '').strip()
    raw_material = (data.get('raw_material') or '').strip()
    if not category or not product_name or not raw_material:
        return jsonify({'success': False, 'message': 'Category, Product Name, and Raw Material are required.'}), 400

    dup = _scoped_query().filter(
        ProductRecipe.id != item_id,
        db.func.lower(db.func.trim(ProductRecipe.category)) == category.lower(),
        db.func.lower(db.func.trim(ProductRecipe.product_name)) == product_name.lower(),
        db.func.lower(db.func.trim(ProductRecipe.raw_material)) == raw_material.lower(),
    ).first()
    if dup:
        return jsonify({'success': False, 'message': f'"{raw_material}" is already mapped to "{product_name}".'}), 400

    raw_map, _ = _raw_items_lookup()
    item.category = category
    item.product_name = product_name
    item.raw_item_id = raw_map.get(raw_material.lower())
    item.raw_material = raw_material
    item.recipe_qty = _to_float(data.get('recipe_qty'), 0.0)
    item.recipe_uom = (data.get('recipe_uom') or '').strip()
    item.updated_at = datetime.now(ZoneInfo("Asia/Manila"))
    db.session.commit()

    return jsonify({'success': True, 'message': 'Recipe item updated.', 'item': item.to_dict()})


@product_recipes_bp.route('/delete/<int:item_id>', methods=['POST'])
@login_required
def delete_recipe(item_id):
    if not _can_access():
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    item = _scoped_query().filter_by(id=item_id).first()
    if not item:
        return jsonify({'success': False, 'message': 'Recipe item not found.'}), 404

    db.session.delete(item)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Recipe item deleted.'})


@product_recipes_bp.route('/upload', methods=['POST'])
@login_required
def upload_excel():
    """Upload product recipe Excel (Category, Product name, Raw Material, Measurement/Order, UOM2)."""
    if not _can_access():
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'success': False, 'message': 'Please select an Excel (.xlsx) file.'}), 400
    if not file.filename.lower().endswith(('.xlsx', '.xlsm')):
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
        missing = [f for f in ('category', 'product_name', 'raw_material') if f not in col_map]
        if missing:
            return jsonify({
                'success': False,
                'message': 'Missing required columns. Expected: Category, Product name, Raw Material, Measurement/Order, UOM2.'
            }), 400

        existing_keys = set()
        if not replace_existing:
            existing_keys = {
                ((c or '').strip().lower(), (p or '').strip().lower(), (m or '').strip().lower())
                for c, p, m in _scoped_query().with_entities(
                    ProductRecipe.category, ProductRecipe.product_name, ProductRecipe.raw_material
                ).all()
            }

        raw_map, _ = _raw_items_lookup()
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

            category = str(cell('category') or '').strip()
            product_name = str(cell('product_name') or '').strip()
            raw_material = str(cell('raw_material') or '').strip()

            if not product_name or not raw_material:
                skipped += 1
                continue

            cat_val = category or 'Uncategorized'
            key = (cat_val.lower(), product_name.lower(), raw_material.lower())
            if key in existing_keys or key in seen_in_upload:
                duplicates += 1
                continue
            seen_in_upload.add(key)

            new_items.append(ProductRecipe(
                company_id=current_user.company_id,
                category=cat_val,
                product_name=product_name,
                raw_item_id=raw_map.get(raw_material.lower()),
                raw_material=raw_material,
                recipe_qty=_to_float(cell('recipe_qty'), 0.0),
                recipe_uom=str(cell('recipe_uom') or '').strip(),
                created_by=current_user.full_name,
                created_at=now_ph,
                updated_at=now_ph,
            ))

        wb.close()

        if not new_items:
            msg = (
                f'No new recipes imported ({duplicates} duplicate(s) skipped).'
                if duplicates else
                'No valid recipe rows were found in the Excel file.'
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
            'message': f'Imported {len(new_items)} recipe mapping(s){suffix}'
        })

    except Exception as exc:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Failed to process Excel file: {exc}'}), 400


@product_recipes_bp.route('/download-sample', methods=['GET'])
@login_required
def download_sample():
    if not _can_access():
        flash('Access denied.', 'error')
        return redirect(url_for('main.dashboard'))

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Product Recipes'
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

    widths = [20, 22, 42, 18, 12]
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(idx)].width = width

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name='product_recipes_sample.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


@product_recipes_bp.route('/export', methods=['GET'])
@login_required
def export_excel():
    if not _can_access():
        flash('Access denied.', 'error')
        return redirect(url_for('main.dashboard'))

    q = (request.args.get('q') or '').strip().lower()
    cat = (request.args.get('category') or '').strip()
    prod = (request.args.get('product_name') or '').strip()

    query = _scoped_query()
    if cat:
        query = query.filter(ProductRecipe.category == cat)
    if prod:
        query = query.filter(ProductRecipe.product_name == prod)

    items = query.order_by(ProductRecipe.category.asc(), ProductRecipe.product_name.asc(), ProductRecipe.id.asc()).all()
    if q:
        items = [
            r for r in items
            if q in f"{r.category or ''} {r.product_name or ''} {r.raw_material or ''} {r.recipe_uom or ''}".lower()
        ]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Product Recipes'
    ws.append(SAMPLE_HEADERS)

    header_fill = PatternFill(start_color='18181B', end_color='18181B', fill_type='solid')
    header_font = Font(bold=True, color='FFFFFF')
    for col_idx in range(1, len(SAMPLE_HEADERS) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='left', vertical='center')

    for r in items:
        ws.append([
            r.category or '',
            r.product_name or '',
            r.raw_material or '',
            float(r.recipe_qty or 0),
            r.recipe_uom or '',
        ])

    widths = [20, 24, 42, 18, 12]
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(idx)].width = width

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name='product_recipes_export.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
