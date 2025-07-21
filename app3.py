from dotenv import load_dotenv
import os

# ───── Load environment variables ─────
load_dotenv()
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_dance.contrib.google import make_google_blueprint, google

# ───── Config ─────
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///taskdb.db"
app.config["SECRET_KEY"] = "supersecretkey"
app.config["SESSION_COOKIE_SECURE"] = False
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

db = SQLAlchemy(app)

# ───── Google OAuth ─────
google_bp = make_google_blueprint(
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    redirect_to="home",
    scope=[
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
        "openid",
    ],
)
app.register_blueprint(google_bp, url_prefix="/login")

# ───── Models ─────
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(100), unique=True)
    username = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(200))
    status = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    modified_at = db.Column(db.DateTime, default=datetime.utcnow)


class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    due_date = db.Column(db.Date)
    priority = db.Column(db.String(10))
    status = db.Column(db.String(10), default="pending")
    category = db.Column(db.String(50))
    collaborators = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

# ───── Routes ─────
@app.route("/")
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip()
        username = request.form["username"].strip()
        password = request.form["password"].strip()

        if User.query.filter((User.username == username) | (User.email == email)).first():
            flash("Username or Email already exists.")
            return redirect(url_for("signup"))

        hashed_pw = generate_password_hash(password)
        user = User(name=name, email=email, username=username, password=hashed_pw, status="active")
        db.session.add(user)
        db.session.commit()
        flash("Signup successful! Please login.")
        return redirect(url_for("login"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        identifier = request.form["username"].strip()
        password = request.form["password"].strip()

        user = User.query.filter(
            (User.username == identifier) | (User.email == identifier)
        ).first()

        if user and check_password_hash(user.password, password):
            session.permanent = True
            session["user_id"] = user.id
            flash("Login successful!")
            return redirect(url_for("tasks"))

        flash("Invalid credentials.")
        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/home")
def home():
    if not google.authorized:
        return redirect(url_for("login"))

    resp = google.get("/oauth2/v2/userinfo")
    assert resp.ok, resp.text
    info = resp.json()

    email = info["email"]
    name = info["name"]

    user = User.query.filter_by(email=email).first()
    if not user:
        username = email.split("@")[0]
        while User.query.filter_by(username=username).first():
            username += "1"

        user = User(name=name, email=email, username=username, password="", status="active")
        db.session.add(user)
        db.session.commit()

    session["user_id"] = user.id
    return redirect(url_for("tasks"))


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    flash("Logged out.")
    return redirect(url_for("login"))


@app.route("/tasks")
def tasks():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]
    user = User.query.get(user_id)
    priority = request.args.get("priority")
    search_query = request.args.get("search")

    task_query = Task.query.filter(
        (Task.user_id == user_id) |
        (Task.collaborators.contains(user.email))
    )

    if priority:
        task_query = task_query.filter_by(priority=priority)

    if search_query:
        search = f"%{search_query}%"
        task_query = task_query.filter(
            (Task.title.ilike(search)) | (Task.description.ilike(search))
        )

    tasks = task_query.order_by(Task.due_date).all()

    return render_template("tasks.html", tasks=tasks, user=user)


@app.route("/add-task", methods=["GET", "POST"])
def add_task():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        title = request.form["title"]
        description = request.form["description"]
        due_date = datetime.strptime(request.form["due_date"], "%Y-%m-%d")
        priority = request.form["priority"]
        category = request.form["category"]
        collaborators = request.form["collaborators"]

        task = Task(
            title=title,
            description=description,
            due_date=due_date,
            priority=priority,
            category=category,
            collaborators=collaborators,
            user_id=session["user_id"],
        )
        db.session.add(task)
        db.session.commit()
        flash("Task added.")
        return redirect(url_for("tasks"))

    return render_template("add_task.html")


@app.route("/edit-task/<int:task_id>", methods=["GET", "POST"])
def edit_task(task_id):
    task = Task.query.get_or_404(task_id)

    if request.method == "POST":
        task.title = request.form["title"]
        task.description = request.form["description"]
        task.due_date = datetime.strptime(request.form["due_date"], "%Y-%m-%d")
        task.priority = request.form["priority"]
        task.category = request.form["category"]
        task.collaborators = request.form["collaborators"]
        db.session.commit()
        flash("Task updated!")
        return redirect(url_for("tasks"))

    return render_template("edit_task.html", task=task)


@app.route("/delete-task/<int:task_id>")
def delete_task(task_id):
    task = Task.query.get_or_404(task_id)
    db.session.delete(task)
    db.session.commit()
    flash("Task deleted!")
    return redirect(url_for("tasks"))


@app.route("/toggle-task/<int:task_id>")
def toggle_task(task_id):
    task = Task.query.get_or_404(task_id)
    task.status = "done" if task.status == "pending" else "pending"
    db.session.commit()
    return redirect(url_for("tasks"))

# ───── Run ─────
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
