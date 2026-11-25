from flask import Blueprint, url_for
from flask_login import login_required
from models import TransOutRecord
from routes.movement_sheet import handle_index, handle_list, handle_submit, handle_delete, handle_export

trans_out_bp = Blueprint('trans_out', __name__, url_prefix='/user/trans-out')


@trans_out_bp.route('', methods=['GET'])
@login_required
def index():
    return handle_index(TransOutRecord, {
        'active_page': 'trans_out',
        'page_title': 'Trans - Out',
        'page_subtitle': 'Enter transfer-out quantities & costs',
        'page_icon': 'fa-right-from-bracket',
        'index_url': url_for('trans_out.index'),
        'list_url': url_for('trans_out.list_records'),
        'submit_url': url_for('trans_out.submit_records'),
        'delete_base': '/user/trans-out/delete/',
        'export_url': url_for('trans_out.export_excel'),
    })


@trans_out_bp.route('/list', methods=['GET'])
@login_required
def list_records():
    return handle_list(TransOutRecord)


@trans_out_bp.route('/submit', methods=['POST'])
@login_required
def submit_records():
    return handle_submit(TransOutRecord, 'trans_out', 'Trans - Out')


@trans_out_bp.route('/delete/<int:record_id>', methods=['POST'])
@login_required
def delete_record(record_id):
    return handle_delete(TransOutRecord, 'trans_out', record_id)


@trans_out_bp.route('/export', methods=['GET'])
@login_required
def export_excel():
    return handle_export(TransOutRecord, 'Trans - Out', 'trans_out')
