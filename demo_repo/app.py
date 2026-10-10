import logging

from flask import Flask, jsonify, render_template, request, session

import config
import db
from services import analytics

app = Flask(__name__)
app.config["SECRET_KEY"] = config.SECRET_KEY
app.config["DEBUG"] = config.DEBUG

logging.basicConfig(filename="shoplite.log", level=logging.INFO)
log = logging.getLogger("shoplite")


@app.before_request
def track_request():
    user_id = session.get("user_id")
    db.record_access(user_id, request.remote_addr, request.path)


@app.get("/signup")
def signup_form():
    return render_template("signup.html")


@app.post("/signup")
def signup():
    form = request.form
    user_id = db.create_user(
        email=form["email"],
        password=form["password"],
        full_name=form["full_name"],
        date_of_birth=form["date_of_birth"],
        ssn=form["ssn"],
        annual_income=int(form["annual_income"]),
        marketing_opt_in=1 if form.get("marketing") else 0,
    )
    log.info(
        "New signup id=%s email=%s ssn=%s dob=%s",
        user_id,
        form["email"],
        form["ssn"],
        form["date_of_birth"],
    )
    session["user_id"] = user_id
    analytics.track("signup", db.get_user(user_id), request.remote_addr)
    return jsonify({"id": user_id}), 201


@app.post("/login")
def login():
    user = db.get_user_by_email(request.form["email"])
    if not db.check_password(user, request.form["password"]):
        return jsonify({"error": "invalid credentials"}), 401
    session["user_id"] = user["id"]
    return jsonify({"id": user["id"]})


@app.get("/users/<int:user_id>/data")
def export_user_data(user_id):
    user = db.get_user(user_id)
    if user is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(
        {
            "profile": dict(user),
            "orders": [dict(order) for order in db.orders_for(user_id)],
        }
    )


@app.post("/account/delete")
def delete_account():
    user_id = session.get("user_id")
    if user_id is None:
        return jsonify({"error": "not signed in"}), 401
    db.mark_deleted(user_id)
    session.clear()
    return jsonify({"status": "deleted"})


@app.post("/privacy/do-not-sell")
def do_not_sell():
    user_id = session.get("user_id")
    if user_id is None:
        return jsonify({"error": "not signed in"}), 401
    with db.connect() as conn:
        conn.execute("UPDATE users SET do_not_sell = 1 WHERE id = ?", (user_id,))
    return jsonify({"status": "recorded"})


if __name__ == "__main__":
    db.init_db()
    app.run()
