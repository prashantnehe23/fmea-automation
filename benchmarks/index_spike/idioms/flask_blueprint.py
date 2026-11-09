from flask import Blueprint
bp = Blueprint("bp", __name__)


@bp.post("/h")
def h():
    return "h"
