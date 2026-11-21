from flask import Blueprint
bp = Blueprint("bp", __name__, url_prefix="/bp")


@bp.post("/h")
def h():
    return "h"
