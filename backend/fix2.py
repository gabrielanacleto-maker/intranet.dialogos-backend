from database import get_connection
db = get_connection()
r = db.execute("SELECT is_admin, is_rh, is_admin_user FROM users WHERE key='gabriel'").fetchone()
print(dict(r))