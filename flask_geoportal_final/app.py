
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory
import sqlite3
import os
import requests

app = Flask(__name__)
app.secret_key = "secret"

ADMIN_LOGIN = "admin"
ADMIN_PASSWORD = "admin123"

UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

GEOSERVER_REST_URL = "http://localhost:8080/geoserver/rest"
GEOSERVER_WORKSPACE = "PFE"
GEOSERVER_USER = "admin"
GEOSERVER_PASSWORD = "geoserver"

DB_PATH = "users.db"

def get_layer_bbox(layer_name):
    url = f"http://localhost:8080/geoserver/rest/layers/{layer_name}.json"
    r = requests.get(url, auth=(GEOSERVER_USER, GEOSERVER_PASSWORD))
    if not r.ok:
        return None
    layer_json = r.json()
    resource_url = layer_json["layer"]["resource"]["href"]
    r2 = requests.get(resource_url, auth=(GEOSERVER_USER, GEOSERVER_PASSWORD))
    if not r2.ok:
        return None
    bbox = r2.json()["featureType"]["latLonBoundingBox"]
    return [
        [bbox["miny"], bbox["minx"]],
        [bbox["maxy"], bbox["maxx"]],
    ]

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# --- Création des tables ---
with get_db() as db:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE,
            password TEXT,
            societe TEXT,
            No_projet  INTEGER
        );
        CREATE TABLE IF NOT EXISTS layer_permissions (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            layer_name TEXT,
            can_download INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            url TEXT,
            label TEXT,
            can_download INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            doc_id INTEGER,
            comment TEXT,
            date DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS layer_feedback (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            layer_name TEXT,
            comment TEXT,
            date DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

# --------- Ajout automatique de colonnes ---------
def get_all_layers_from_geoserver():
    url = f"{GEOSERVER_REST_URL}/workspaces/{GEOSERVER_WORKSPACE}/layers.json"
    try:
        r = requests.get(url, auth=(GEOSERVER_USER, GEOSERVER_PASSWORD), timeout=5)
        if r.ok:
            data = r.json()
            return [layer["name"] for layer in data["layers"]["layer"]]
    except Exception:
        pass
    return []

def safe_add_column(conn, table, column_def):
    column = column_def.split()[0]
    cur = conn.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cur.fetchall()]
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
        print(f"[INFO] Colonne '{column}' ajoutée à la table '{table}'.")

with get_db() as db:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE,
            password TEXT
            -- autres colonnes si besoin
        );
        -- autres tables...
        """
    )
    # Migration automatique :
    safe_add_column(db, "users", "societe TEXT")
    safe_add_column(db, "users", "No_projet INTEGER")



@app.route('/')
def home():
    return render_template('index.html')
# --------- ADMIN AUTH ---------
@app.route("/admin_login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        login = request.form["login"]
        password = request.form["password"]
        if login == ADMIN_LOGIN and password == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin_dashboard"))
        else:
            error = "Identifiants incorrects"
    return render_template("admin_login.html", error=error)

@app.route("/admin_logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin_login"))

# --------- ADMIN DASHBOARD ---------
@app.route("/admin/dashboard")
def admin_dashboard():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    return render_template("admin_dashboard.html")

# --------- ADMIN (ANCIENNE ROUTE : REDIRIGE) ---------
@app.route("/admin", methods=["GET", "POST"])
def admin():
    # Redirige directement vers le dashboard moderne
    return redirect(url_for("admin_dashboard"))

# --------- CREATION UTILISATEUR ---------
@app.route("/admin/create_user", methods=["GET", "POST"])
def admin_create_user():
    if "admin" not in session:
        return redirect(url_for("admin_login"))
    message = ""
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        societe = request.form["societe"]
        No_projet = request.form["No_projet"]
        email = request.form["email"] 
        with get_db() as db:
            db.execute(
                "INSERT INTO users (username, password, societe,No_projet, email) VALUES (?, ?, ?, ?, ?)",
                (username, password, societe, No_projet,email)
            )
        message = "Nouvel utilisateur créé ✅"
    return render_template("admin_create_user.html", message=message)



# --------- AVIS ---------
@app.route("/admin/feedbacks")
def admin_feedbacks():
    if "admin" not in session:
        return redirect(url_for("admin_login"))
    with get_db() as db:
        feedbacks = db.execute("""
            SELECT f.id, f.comment, f.date, u.username, d.label AS document
            FROM feedback f
            JOIN users u ON f.user_id = u.id
            LEFT JOIN documents d ON f.doc_id = d.id
            ORDER BY f.date DESC
        """).fetchall()
        layer_feedbacks = db.execute("""
            SELECT lf.id, lf.comment, lf.date, u.username, lf.layer_name
            FROM layer_feedback lf
            JOIN users u ON lf.user_id = u.id
            ORDER BY lf.date DESC
        """).fetchall()
    return render_template("admin_feedbacks.html", feedbacks=feedbacks, layer_feedbacks=layer_feedbacks)


# --------- GESTION UTILISATEURS ---------
@app.route("/admin/manage_users")
def admin_manage_users():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    with get_db() as db:
        users = db.execute("SELECT id, username FROM users").fetchall()
    return render_template("admin_manage_users.html", users=users)

@app.route("/admin/edit/<int:uid>", methods=["GET", "POST"])
def edit_user(uid):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    layers_available = get_all_layers_from_geoserver()
    message = ""
    with get_db() as db:
        if request.method == "POST":
            # --- SUPPRESSION d'un fichier partagé ---
            if "delete_doc" in request.form:
                doc_id = request.form["delete_doc"]
                db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
                message = "✅ Fichier supprimé."
            else:
                # --- Récupération des données du formulaire ---
                password = request.form.get("password")
                layers_selected = request.form.getlist("layers_selected")
                # MAJ du mot de passe si rempli
                if password:
                    db.execute("UPDATE users SET password=? WHERE id=?", (password, uid))
                # MAJ email (correctement récupéré)
                email_val = request.form.get("email")
                if email_val:
                   db.execute("UPDATE users SET email=? WHERE id=?", (email_val, uid))

                # MAJ des couches partagées
                db.execute("DELETE FROM layer_permissions WHERE user_id=?", (uid,))
                for layer in layers_selected:
                    can_dl = 1 if request.form.get(f"dl_{layer}") == "on" else 0
                    db.execute(
                        "INSERT INTO layer_permissions (user_id, layer_name, can_download) VALUES (?, ?, ?)",
                        (uid, layer, can_dl)
                    )
                # Gestion des fichiers uploadés (multi)
                if "shared_files" in request.files:
                    files = request.files.getlist("shared_files")
                    for file_obj in files:
                        if file_obj and file_obj.filename:
                            filename = file_obj.filename
                            save_path = os.path.join(UPLOAD_FOLDER, filename)
                            file_obj.save(save_path)
                            public_url = f"/uploads/{filename}"
                            db.execute(
                                "INSERT INTO documents (user_id, url, label, can_download) VALUES (?, ?, ?, ?)",
                                (uid, public_url, filename, 1)
                            )
                # MAJ droit de téléchargement pour fichiers déjà partagés
                for doc in db.execute("SELECT id, label FROM documents WHERE user_id=?", (uid,)):
                    can_dl = 1 if request.form.get(f"dl_file_{doc['label']}") == "on" else 0
                    db.execute("UPDATE documents SET can_download=? WHERE id=?", (can_dl, doc["id"]))
                message = "✅ Modifications enregistrées avec succès."
        # --- Rechargement pour affichage (GET ou après POST) ---
        user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        perms = db.execute("SELECT layer_name, can_download FROM layer_permissions WHERE user_id=?", (uid,))
        layers_user = [row["layer_name"] for row in perms]
        dl_rights = {row["layer_name"]: row["can_download"] for row in perms}
        docs_query = db.execute("SELECT id, url, label, can_download FROM documents WHERE user_id=?", (uid,))
        docs_user = []
        for row in docs_query:
            feedbacks = db.execute("SELECT comment, date FROM feedback WHERE doc_id=?", (row["id"],)).fetchall()
            docs_user.append({
                "id": row["id"],
                "url": row["url"],
                "label": row["label"],
                "can_download": row["can_download"],
                "feedbacks": feedbacks
            })
        layer_feedbacks = {}
        for lyr in layers_user:
            feedbacks = db.execute("SELECT comment, date FROM layer_feedback WHERE layer_name=?", (lyr,)).fetchall()
            layer_feedbacks[lyr] = feedbacks
    return render_template(
        "admin_edit.html",
        user=user,
        layers_available=layers_available,
        layers_user=layers_user,
        dl_rights=dl_rights,
        docs_user=docs_user,
        layer_feedbacks=layer_feedbacks,
        message=message
    )


@app.route("/admin/<int:uid>/delete_doc/<int:doc_id>", methods=["POST"])
def delete_doc(uid, doc_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    with get_db() as db:
        db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    return redirect(url_for("edit_user", uid=uid))


@app.route("/admin/delete_user/<int:uid>")
def delete_user(uid):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    with get_db() as db:
        db.execute("DELETE FROM documents WHERE user_id=?", (uid,))
        db.execute("DELETE FROM layer_permissions WHERE user_id=?", (uid,))
        db.execute("DELETE FROM users WHERE id=?", (uid,))
    return redirect(url_for("admin_manage_users"))
## --------- ADMIN FEEDBACKS ---------


@app.route('/admin/delete_feedback/<int:feedback_id>', methods=['POST'])
def admin_delete_feedback(feedback_id):
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    with get_db() as db:
        db.execute('DELETE FROM feedback WHERE id = ?', (feedback_id,))
    return redirect(url_for('admin_feedbacks'))

@app.route('/admin/delete_layer_feedback/<int:feedback_id>', methods=['POST'])
def admin_delete_layer_feedback(feedback_id):
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    with get_db() as db:
        db.execute('DELETE FROM layer_feedback WHERE id = ?', (feedback_id,))
    return redirect(url_for('admin_feedbacks'))

# --------- UTILISATEUR STANDARD ---------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user, pwd = request.form["username"], request.form["password"]
        with get_db() as db:
            row = db.execute("SELECT * FROM users WHERE username=? AND password=?", (user, pwd)).fetchone()
        if row:
            session["username"] = user
            return redirect(url_for("index"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
def index():
    if "username" not in session:
        return redirect(url_for("login"))
    with get_db() as db:
        uid = db.execute("SELECT id FROM users WHERE username = ?", (session["username"],)).fetchone()["id"]
        user_layers = db.execute(
           "SELECT 'PFE:' || layer_name AS layer_name, can_download FROM layer_permissions WHERE user_id = ?", (uid,)
        ).fetchall()

        user_layers = [(row["layer_name"], row["can_download"]) for row in user_layers]
        layer_bboxes = []
        for layer, _ in user_layers:
            bbox = get_layer_bbox(layer)
            if bbox:
                layer_bboxes.append(bbox)
        docs = [(row["url"], row["label"], row["can_download"])
                for row in db.execute("SELECT url, label, can_download FROM documents WHERE user_id = ?", (uid,))]
    return render_template("index.html", username=session["username"], user_layers=user_layers, docs=docs, layer_bboxes=layer_bboxes)

# --------- TELECHARGEMENT/LECTURE FICHIER ---------
@app.route("/uploads/view/<filename>")
def view_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route("/uploads/download/<filename>")
def download_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=True)

# --------- AVIS UTILISATEUR ---------
@app.route("/feedback/<path:doc_url>", methods=["POST"])
def feedback(doc_url):
    if "username" not in session:
        return redirect(url_for("login"))
    comment = request.form["comment"]
    with get_db() as db:
        uid = db.execute("SELECT id FROM users WHERE username = ?", (session["username"],)).fetchone()["id"]
        doc = db.execute("SELECT id FROM documents WHERE url = ?", (doc_url,)).fetchone()
        if doc:
            db.execute("INSERT INTO feedback (user_id, doc_id, comment) VALUES (?, ?, ?)", (uid, doc["id"], comment))
    return redirect(url_for("index"))

@app.route("/layer_feedback/<layer_name>", methods=["POST"])
def layer_feedback(layer_name):
    if "username" not in session:
        return redirect(url_for("login"))
    comment = request.form["comment"]
    with get_db() as db:
        uid = db.execute("SELECT id FROM users WHERE username = ?", (session["username"],)).fetchone()["id"]
        db.execute("INSERT INTO layer_feedback (user_id, layer_name, comment) VALUES (?, ?, ?)", (uid, layer_name, comment))
    return redirect(url_for("index"))

@app.route("/admin/profile", methods=["GET", "POST"])
def admin_profile():
    if "admin" not in session:
        return redirect(url_for("admin_login"))
    # Pour l'exemple on suppose que l'identifiant et le mot de passe sont en dur
    # (Sinon, il faut les stocker et lire dans la BDD ou un fichier)
    message = ""
    admin_login = ADMIN_LOGIN  # Par défaut
    if request.method == "POST":
        new_login = request.form["login"]
        new_pwd = request.form["password"]
        # Ici tu peux mettre à jour ADMIN_LOGIN et ADMIN_PASSWORD (si stockés dans la BDD ou fichier)
        # Exemple de message, tu peux améliorer la logique selon ta gestion réelle
        message = "Modification prise en compte (redémarrage de l'app requis pour voir les changements en dur)" 
    return render_template("admin_profile.html", admin_login=ADMIN_LOGIN, message=message)


if __name__ == "__main__":
    app.run(debug=True, port=5000, host="0.0.0.0")
