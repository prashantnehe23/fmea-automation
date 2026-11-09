from flask import Flask
app = Flask(__name__)


@app.route("/a", methods=["POST"])
def a():
    return "a"
