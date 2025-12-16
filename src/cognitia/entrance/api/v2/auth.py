"""Authentication API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status

from ...dependencies import get_auth_service, get_current_user
from ...services import AuthService
from ...schemas.auth import (
    RegisterRequest,
    LoginRequest,
    TokenResponse,
    EmailVerificationRequest,
    PasswordResetRequest,
    PasswordResetConfirm,
)
from ...schemas.user import UserResponse
from ...database import User
from ...core.exceptions import (
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    EmailNotVerifiedError,
    InvalidTokenError,
)


router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    request: RegisterRequest,
    auth_service: AuthService = Depends(get_auth_service),
):
    """
    Register a new user.

    Creates a new user account and sends email verification.
    """
    try:
        user, verification_token = await auth_service.register(
            email=request.email,
            password=request.password,
            first_name=request.first_name,
            last_name=request.last_name,
        )

        # Queue email verification task (async background job)
        from ...tasks import send_verification_email
        send_verification_email.delay(
            user_email=user.email,
            user_name=user.first_name or user.email.split('@')[0],
            verification_token=verification_token
        )

        return UserResponse.model_validate(user)

    except EmailAlreadyExistsError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=e.message
        )


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
):
    """
    Login with email and password.

    Returns access and refresh tokens.
    """
    try:
        token_response = await auth_service.login(
            email=request.email,
            password=request.password,
            require_verification=False,  # Allow login without verification in development
        )
        return token_response

    except (InvalidCredentialsError, EmailNotVerifiedError) as e:
        raise HTTPException(
            status_code=e.status_code,
            detail=e.message
        )


@router.post("/verify-email", response_model=UserResponse)
async def verify_email(
    request: EmailVerificationRequest,
    auth_service: AuthService = Depends(get_auth_service),
):
    """
    Verify email address with token.

    Token is sent to user's email during registration.
    """
    try:
        user = await auth_service.verify_email(request.token)
        return UserResponse.model_validate(user)

    except InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=e.message
        )


@router.post("/request-password-reset", status_code=status.HTTP_202_ACCEPTED)
async def request_password_reset(
    request: PasswordResetRequest,
    auth_service: AuthService = Depends(get_auth_service),
):
    """
    Request password reset email.

    Always returns 202 to prevent email enumeration.
    """
    await auth_service.request_password_reset(request.email)

    return {
        "message": "If the email exists, a password reset link has been sent"
    }


@router.post("/reset-password", response_model=UserResponse)
async def reset_password(
    request: PasswordResetConfirm,
    auth_service: AuthService = Depends(get_auth_service),
):
    """
    Reset password with token.

    Token is sent to user's email via request-password-reset.
    """
    try:
        user = await auth_service.reset_password(
            token=request.token,
            new_password=request.new_password
        )
        return UserResponse.model_validate(user)

    except InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=e.message
        )


@router.post("/refresh", response_model=dict)
async def refresh_token(
    refresh_token: str,
    auth_service: AuthService = Depends(get_auth_service),
):
    """
    Refresh access token using refresh token.

    Returns a new access token.
    """
    try:
        new_access_token = await auth_service.refresh_access_token(refresh_token)
        return {"access_token": new_access_token, "token_type": "bearer"}

    except InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=e.message
        )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
):
    """
    Get current authenticated user information.

    Requires valid access token in Authorization header.
    """
    return UserResponse.model_validate(current_user)
