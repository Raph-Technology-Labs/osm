from fastapi import APIRouter

router = APIRouter()


@router.get("/test")
def test_api():
    return {"message": "Frontend Backend Connected Successfully"}