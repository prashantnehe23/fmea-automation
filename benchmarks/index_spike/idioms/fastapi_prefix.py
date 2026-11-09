from fastapi import APIRouter
router = APIRouter(prefix="/v1")


@router.get("/b")
def b():
    return "b"
