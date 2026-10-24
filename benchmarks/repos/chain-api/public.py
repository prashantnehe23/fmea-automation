import requests
from flask import Flask, request

app = Flask(__name__)


@app.get("/preview")
def preview():
    url = request.args["url"]
    resp = requests.get(url, timeout=5)
    return resp.text[:2000]
