from flask import Blueprint, url_for
from flask_login import login_required
from models import TransInRecord
from routes.movement_sheet import handle_index, handle_list, handle_submit, handle_delete, handle_export

trans_in_bp = Blueprint('trans_in', __name__, url_prefix='/user/trans-in')


@trans_in_bp.route('', methods=['GET'])
@login_required
def index():
    return handle_index(TransInRecord, {
        'active_page': 'trans_in',
        'page_title': 'Trans - In',
        'page_subtitle': 'Enter purchase quantities & costs',
        'page_icon': 'fa-cart-plus',
        'index_url': url_for('trans_in.index'),
        'list_url': url_for('trans_in.list_records'),
        'submit_url': url_for('trans_in.submit_purchases'),
        'delete_base': '/user/trans-in/delete/',
        'export_url': url_for('trans_in.export_excel'),
    })


@trans_in_bp.route('/list', methods=['GET'])
@login_required
def list_records():
    return handle_list(TransInRecord)


@trans_in_bp.route('/submit', methods=['POST'])
@login_required
def submit_purchases():
    return handle_submit(TransInRecord, 'trans_in', 'Trans - In')


@trans_in_bp.route('/delete/<int:record_id>', methods=['POST'])
@login_required
def delete_record(record_id):
    return handle_delete(TransInRecord, 'trans_in', record_id)


@trans_in_bp.route('/export', methods=['GET'])
@login_required
def export_excel():
    return handle_export(TransInRecord, 'Trans - In', 'trans_in')
