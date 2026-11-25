# Standard library imports
import io
from datetime import datetime
from zoneinfo import ZoneInfo

# Third-party imports
from flask import render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_login import current_user
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

# Local imports
from extensions import db
from models import RawItem, DailyEndingInventory, Requisition


def can_access():
    return current_user.is_authenticated and current_user.role in ('User', 'SYS-Admin')


def to_float(val, default=0.0):
    if val is None or str(val).strip() == '':
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def parse_date(date_str):
    if date_str:
        try:
            return datetime.strptime(date_str.strip(), '%Y-%m-%d').date()
        except ValueError:
            pass
    return datetime.now(ZoneInfo("Asia/Manila")).date()


def scoped_query(model_cls):
    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        return model_cls.query
    return model_cls.query.filter_by(company_id=current_user.company_id)


def raw_items_list():
    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        items = RawItem.query.order_by(RawItem.raw_material.asc()).all()
    else:
        items = RawItem.query.filter_by(company_id=current_user.company_id).order_by(RawItem.raw_material.asc()).all()

    seen = set()
    unique = []
    for item in items:
        name = (item.raw_material or '').strip()
        key = name.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append({'id': item.id, 'raw_material': name, 'uom': item.uom or ''})
    return unique


def build_sheet_rows(model_cls, target_date):
    """Return saved rows for target_date (empty list if none yet)."""
    saved_rows = scoped_query(model_cls).filter(
        model_cls.trans_date == target_date
    ).order_by(model_cls.id.asc()).all()

    return [
        {
            'id': r.id,
            'raw_item_id': r.raw_item_id,
            'raw_item_name': r.raw_item_name or '',
            'uom': r.uom or '',
            'qty': float(r.qty or 0),
            'cost': float(r.cost or 0),
            'total_cost': float(r.total_cost or 0),
            'remarks': r.remarks or '',
        }
        for r in saved_rows
    ]


def sync_daily_ending_field(company_id, target_date, raw_item_id, raw_item_name, field_name, exact_qty):
    """Set DAILY ENDING INVENTORY.<field_name> to exact_qty and recompute THEO & variance."""
    existing = None
    if raw_item_id is not None:
        existing = DailyEndingInventory.query.filter_by(
            company_id=company_id,
            inventory_date=target_date,
            raw_item_id=raw_item_id
        ).first()
    if not existing:
        existing = DailyEndingInventory.query.filter_by(
            company_id=company_id,
            inventory_date=target_date,
            raw_item_name=raw_item_name
        ).first()

    now_ph = datetime.now(ZoneInfo("Asia/Manila"))
    if existing:
        setattr(existing, field_name, exact_qty)
        existing.theoretical_ending = (
            float(existing.beg or 0)
            + float(existing.trans_in or 0)
            - float(existing.trans_out or 0)
            - float(existing.wastage or 0)
            - float(existing.sold or 0)
        )
        if existing.actual_ending is not None:
            existing.variance = float(existing.actual_ending) - existing.theoretical_ending
        existing.updated_by = current_user.full_name
        existing.updated_at = now_ph
    elif exact_qty > 0:
        kwargs = {
            'company_id': company_id,
            'inventory_date': target_date,
            'raw_item_id': raw_item_id,
            'raw_item_name': raw_item_name,
            'beg': 0.0,
            'trans_in': 0.0,
            'trans_out': 0.0,
            'wastage': 0.0,
            'sold': 0.0,
            'actual_ending': None,
            'variance': None,
            'remarks': '',
            'updated_by': current_user.full_name,
            'updated_at': now_ph,
        }
        kwargs[field_name] = exact_qty
        kwargs['theoretical_ending'] = (
            kwargs['beg'] + kwargs['trans_in'] - kwargs['trans_out'] - kwargs['wastage'] - kwargs['sold']
        )
        db.session.add(DailyEndingInventory(**kwargs))


def handle_index(model_cls, cfg):
    if not can_access():
        flash('Access denied.', 'error')
        return redirect(url_for('main.dashboard'))

    target_date = parse_date(request.args.get('date'))
    rows = build_sheet_rows(model_cls, target_date)

    pending_receiving_count = Requisition.query.filter(
        (Requisition.company_id == current_user.company_id) |
        (Requisition.destination_company_id == current_user.company_id),
        Requisition.status.in_(['Dispatched', 'dispatched', 'Partial', 'partial'])
    ).count() if current_user.company_id else 0

    return render_template(
        'user/movement_sheet.html',
        trans_date=target_date.strftime('%Y-%m-%d'),
        sheet_rows=rows,
        raw_items=raw_items_list(),
        pending_receiving_count=pending_receiving_count,
        **cfg,
    )


def handle_list(model_cls):
    if not can_access():
        return jsonify({'success': False, 'message': 'Access denied.'}), 403
    target_date = parse_date(request.args.get('date'))
    rows = build_sheet_rows(model_cls, target_date)
    return jsonify({'success': True, 'items': rows, 'total': len(rows)})


def handle_submit(model_cls, daily_field, label):
    if not can_access():
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    payload = request.get_json(silent=True) or {}
    trans_date = parse_date(payload.get('date'))
    items = payload.get('items') or []

    if not isinstance(items, list):
        return jsonify({'success': False, 'message': 'Invalid items payload.'}), 400

    for row in items:
        raw_name = (row.get('raw_item_name') or '').strip()
        if not raw_name:
            continue
        qty = to_float(row.get('qty'), 0.0)
        cost = to_float(row.get('cost'), 0.0)
        if qty <= 0 or cost <= 0:
            return jsonify({
                'success': False,
                'message': f'"{raw_name}" is missing Qty or Cost (both must be greater than 0).'
            }), 400

    now_ph = datetime.now(ZoneInfo("Asia/Manila"))
    raw_lookup = {r['raw_material'].lower(): r for r in raw_items_list()}

    prev_rows = scoped_query(model_cls).filter(model_cls.trans_date == trans_date).all()
    prev_names = {(r.raw_item_id, (r.raw_item_name or '').strip()) for r in prev_rows}

    scoped_query(model_cls).filter(model_cls.trans_date == trans_date).delete(synchronize_session=False)

    saved_count = 0
    new_names = set()

    for row in items:
        raw_name = (row.get('raw_item_name') or '').strip()
        if not raw_name:
            continue

        matched = raw_lookup.get(raw_name.lower())
        raw_item_id = matched['id'] if matched else row.get('raw_item_id')
        uom = (row.get('uom') or (matched['uom'] if matched else '')).strip()
        qty = to_float(row.get('qty'), 0.0)
        cost = to_float(row.get('cost'), 0.0)
        remarks = (row.get('remarks') or '').strip()
        total_cost = qty * cost

        db.session.add(model_cls(
            company_id=current_user.company_id,
            trans_date=trans_date,
            raw_item_id=raw_item_id,
            raw_item_name=raw_name,
            qty=qty,
            uom=uom,
            cost=cost,
            total_cost=total_cost,
            remarks=remarks,
            created_by=current_user.full_name,
            created_at=now_ph,
        ))
        sync_daily_ending_field(current_user.company_id, trans_date, raw_item_id, raw_name, daily_field, qty)
        new_names.add((raw_item_id, raw_name))
        saved_count += 1

    for old_id, old_name in prev_names:
        if (old_id, old_name) not in new_names and old_name:
            sync_daily_ending_field(current_user.company_id, trans_date, old_id, old_name, daily_field, 0.0)

    db.session.commit()
    return jsonify({
        'success': True,
        'submitted': saved_count,
        'message': f'Finalized {saved_count} {label} item(s) for {trans_date.strftime("%Y-%m-%d")}.'
    })


def handle_delete(model_cls, daily_field, record_id):
    if not can_access():
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    rec = scoped_query(model_cls).filter_by(id=record_id).first()
    if not rec:
        return jsonify({'success': False, 'message': 'Record not found.'}), 404

    trans_date = rec.trans_date
    company_id = rec.company_id
    raw_item_id = rec.raw_item_id
    raw_item_name = rec.raw_item_name

    db.session.delete(rec)
    db.session.flush()

    remaining_qty = db.session.query(
        db.func.coalesce(db.func.sum(model_cls.qty), 0.0)
    ).filter(
        model_cls.company_id == company_id,
        model_cls.trans_date == trans_date,
        model_cls.raw_item_name == raw_item_name
    ).scalar() or 0.0

    sync_daily_ending_field(company_id, trans_date, raw_item_id, raw_item_name, daily_field, float(remaining_qty))
    db.session.commit()
    return jsonify({'success': True, 'message': f'Deleted "{raw_item_name}" from database.'})


def handle_export(model_cls, sheet_title, file_prefix):
    if not can_access():
        flash('Access denied.', 'error')
        return redirect(url_for('main.dashboard'))

    target_date = parse_date(request.args.get('date'))
    q = (request.args.get('q') or '').strip().lower()
    rows = build_sheet_rows(model_cls, target_date)
    if q:
        rows = [r for r in rows if q in (r['raw_item_name'] or '').lower()]

    headers = ['Date', 'Raw Item', 'UOM', 'Qty', 'Cost', 'Total Cost', 'Remarks']
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_title
    ws.append(headers)

    header_fill = PatternFill(start_color='18181B', end_color='18181B', fill_type='solid')
    header_font = Font(bold=True, color='FFFFFF')
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='left', vertical='center')

    date_str = target_date.strftime('%Y-%m-%d')
    for r in rows:
        ws.append([
            date_str,
            r['raw_item_name'],
            r['uom'],
            r['qty'],
            r['cost'],
            r['total_cost'],
            r['remarks'],
        ])

    widths = [14, 42, 12, 12, 14, 14, 28]
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(idx)].width = width

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name=f'{file_prefix}_{date_str}.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
