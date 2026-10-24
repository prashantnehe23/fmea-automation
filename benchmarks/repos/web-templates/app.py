import os

from flask import Flask, redirect, render_template, request, session

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
app.config["SESSION_COOKIE_HTTPONLY"] = False
COMMENTS = []


@app.post("/comment")
def add_comment():
    COMMENTS.append({"author": request.form["author"], "body": request.form["body"]})
    return redirect("/comments")


@app.get("/comments")
def show_comments():
    return render_template("comments.html", comments=COMMENTS)


@app.get("/admin/moderate")
def moderate():
    if not session.get("is_admin"):
        return "forbidden", 403
    return render_template("comments.html", comments=COMMENTS)
