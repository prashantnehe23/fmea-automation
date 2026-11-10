from fastapi import APIRouter, FastAPI

app = FastAPI()
router = APIRouter()


@router.get("/z")
def z():
    return "z"


app.include_router(router, prefix="/api")
