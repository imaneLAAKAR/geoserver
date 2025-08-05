import sqlite3
from werkzeug.security import generate_password_hash

db = sqlite3.connect("users.db")
cursor = db.cursor()

username = "admin"
password = generate_password_hash("admin123")
role = "admin"

cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", (username, password, role))
db.commit()
db.close()
print("✅ Compte admin créé : admin / admin123")
