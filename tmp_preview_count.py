import os, shutil, sys

src = 'instance/inventory.db'
dst = 'instance/inventory_count_check.db'
if os.path.exists(dst):
    os.remove(dst)
shutil.copy(src, dst)

sys.path.insert(0, '.')
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.abspath(dst).replace('\\', '/')

from app import app
from models import User

app.config['WTF_CSRF_ENABLED'] = False

os.makedirs('.tmp_preview', exist_ok=True)

with app.app_context():
    admin = User.query.filter_by(role='SYS-Admin').first()
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['_user_id'] = str(admin.id)
        r = c.get('/products/products')
        html = r.get_data(as_text=True)
        # Open the count modal on load for the screenshot
        html = html.replace('</body>', '''
<script>
window.addEventListener('load', function() {
  var row = document.querySelector('.product-row');
  if (row) {
    var name = row.querySelector('h6').textContent.trim();
    var qty = row.querySelector('td:nth-child(3) .fw-bold').textContent.trim();
    var uom = row.querySelector('td:nth-child(3) small').textContent.trim();
    openCountModal(row.getAttribute('data-product-id'), name, qty, uom);
  }
});
</script>
</body>''')
        with open('.tmp_preview/count.html', 'w', encoding='utf-8') as f:
            f.write(html)
        print('saved .tmp_preview/count.html')
