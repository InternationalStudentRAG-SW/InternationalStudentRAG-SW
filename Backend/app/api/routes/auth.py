from fastapi import APIRouter, Depends, HTTPException
# from sqlalchemy.orm import Session 
import requests

# DB 관련 임포트 주석 처리
# from app.db.database import get_db
# from app.models.tables.users import User
from app.models.schemas import SignupRequest, LoginRequest, GoogleLoginRequest, AdditionalInfoRequest

router = APIRouter(prefix="/api", tags=["auth"])

@router.post("/signup")
def signup(data: SignupRequest):
    # [DB 로직 주석 처리]
    # existing_user = db.query(User).filter(User.email == data.email).first()
    # if existing_user:
    #     raise HTTPException(status_code=400, detail="이미 가입된 이메일입니다.")

    # new_user = User(
    #     email=data.email,
    #     password_hash=data.password,
    #     social_provider='NONE',
    #     role=data.role.upper(),
    #     nationality=data.nationality,
    #     major=data.major,
    #     status=data.status.upper()
    # )
    
    # try:
    #     db.add(new_user)
    #     db.commit()
    #     db.refresh(new_user)
    #     return {"message": "회원가입 성공!", "user_id": new_user.user_id}
    # except Exception as e:
    #     db.rollback()
    #     raise HTTPException(status_code=500, detail=f"데이터베이스 오류: {str(e)}")
    
    # DB 대신 반환할 가짜 응답
    return {"message": "회원가입 성공! (테스트 모드: DB 미연결)", "user_id": "test-user-id"}

@router.post("/login")
def login(data: LoginRequest):
    # [DB 로직 주석 처리]
    # user = db.query(User).filter(User.email == data.email).first()
    # if not user or user.password_hash != data.password:
    #     raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")
    
    # DB 대신 반환할 가짜 응답
    return {
        "message": "로그인 성공 (테스트 모드: DB 미연결)",
        "access_token": "fake-jwt-token-for-testing", 
        "token_type": "bearer"
    }

@router.post("/google-login")
def google_login(data: GoogleLoginRequest):
    google_url = f"https://www.googleapis.com/oauth2/v3/userinfo?access_token={data.token}"
    response = requests.get(google_url)
    
    if response.status_code != 200:
        raise HTTPException(status_code=400, detail="유효하지 않은 구글 토큰입니다.")
    
    user_info = response.json()
    email = user_info.get("email")

    # [DB 로직 주석 처리]
    # user = db.query(User).filter(User.email == email).first()
    # is_new_user = False 

    # if not user:
    #     is_new_user = True 
    #     user = User(
    #         email=email,
    #         password_hash=None,
    #         social_provider='GOOGLE',
    #         role='STUDENT',
    #         nationality='Unknown', 
    #         major=None,
    #         status='ACTIVE'
    #     )
    #     db.add(user)
    #     db.commit()
    #     db.refresh(user)
    # elif user.nationality == 'Unknown':
    #     is_new_user = True

    # DB 대신 반환할 가짜 응답
    return {
        "message": "구글 로그인 성공 (테스트 모드: DB 미연결)",
        "access_token": "google-token-for-test-user",
        "token_type": "bearer",
        "user_email": email,
        "is_new_user": False  # 테스트 편의를 위해 일단 False로 설정용!
    }

@router.post("/update-additional-info")
def update_additional_info(data: AdditionalInfoRequest):
    # [DB 로직 주석 처리]
    # user = db.query(User).filter(User.email == data.email).first()
    
    # if not user:
    #     raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    
    # user.nationality = data.nationality
    # user.major = data.major
    
    # try:
    #     db.add(user)
    #     db.commit()
    #     return {"message": "정보 업데이트 성공"}
    # except Exception as e:
    #     db.rollback()
    #     raise HTTPException(status_code=500, detail=f"업데이트 중 오류 발생: {str(e)}")
    
    # DB 대신 반환할 가짜 응답
    return {"message": "정보 업데이트 성공 (테스트 모드: DB 미연결)"}