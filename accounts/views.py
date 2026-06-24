from rest_framework import status, generics, permissions
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model

from .serializers import (
    SignupSerializer, VerifyEmailSerializer,
    InitiateEmailUpdateSerializer, VerifyEmailUpdateSerializer,
    DeleteAccountSerializer, UserProfileSerializer
)
from .services import (
    signup_user,
    verify_signup_otp,
    initiate_email_update,
    verify_email_update,
    delete_user_account,
)
from drf_spectacular.utils import extend_schema
from drf_spectacular.types import OpenApiTypes

User = get_user_model()


class SignupView(generics.CreateAPIView):
    """
    Register a new user.

    Accepts `email`, `first_name`, `last_name`, and `password`.
    The account is created **inactive** — the user must verify their email
    with the OTP sent to the provided address (see `/api/verify-email/`).
    """

    serializer_class = SignupSerializer
    permission_classes = [permissions.AllowAny]

    def perform_create(self, serializer):
        signup_user(serializer)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(
            {"detail": "Signup successful. Please verify your email with the OTP sent."},
            status=status.HTTP_201_CREATED
        )


class VerifyEmailView(generics.GenericAPIView):
    """
    Verify a user's email using the OTP they received.

    Required fields: `email` (the address used during signup) and `otp` (6‑digit code).
    On success the account is activated and can log in.
    """
    serializer_class = VerifyEmailSerializer
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        request=VerifyEmailSerializer,
        responses=OpenApiTypes.OBJECT,
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']
        otp_code = serializer.validated_data['otp']

        verify_signup_otp(email, otp_code)
        return Response({"detail": "Email verified successfully. You can now login."}, status=status.HTTP_200_OK)


# Custom login using email
class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    username_field = User.USERNAME_FIELD  # 'email'


class LoginView(TokenObtainPairView):
    """
    Obtain an access and refresh JWT token pair.

    Send `email` and `password` in the request body.
    The response contains `access` (short‑lived) and `refresh` (long‑lived) tokens.
    Pass the `access` token as a `Bearer` authorization header for authenticated endpoints.
    """

    serializer_class = EmailTokenObtainPairSerializer


class InitiateEmailUpdateView(generics.GenericAPIView):
    """
    Request to change the authenticated user's email address.

    Requires a valid JWT token in the `Authorization` header.
    Send `{"new_email": "new@example.com"}`. A new OTP is sent to the new address.
    Complete the update by verifying that OTP via `/api/verify-update-email/`.
    """

    serializer_class = InitiateEmailUpdateSerializer
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=InitiateEmailUpdateSerializer,
        responses=OpenApiTypes.OBJECT,
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_email = serializer.validated_data['new_email']

        initiate_email_update(request.user, new_email)
        return Response({"detail": "OTP sent to new email. Verify to complete update."})


class VerifyEmailUpdateView(generics.GenericAPIView):
    """
    Confirm an email change by submitting the OTP sent to the new address.

    Requires a valid JWT token. Send `{"otp": "123456"}`.
    On success the user's email is permanently updated to the new address.
    """
    serializer_class = VerifyEmailUpdateSerializer
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=VerifyEmailUpdateSerializer,
        responses=OpenApiTypes.OBJECT,
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        otp_code = serializer.validated_data['otp']

        verify_email_update(request.user, otp_code)
        return Response({"detail": "Email updated successfully."})


class DeleteAccountView(generics.GenericAPIView):
    """
    Permanently delete the authenticated user's account.

    Requires a valid JWT token. The request body must contain the current `password`.
    If the password is correct the account is removed immediately.
    """
    serializer_class = DeleteAccountSerializer
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=DeleteAccountSerializer,
        responses=OpenApiTypes.OBJECT,
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        password = serializer.validated_data['password']

        delete_user_account(request.user, password)
        return Response({"detail": "Account deleted."}, status=status.HTTP_204_NO_CONTENT)


class UserProfileView(generics.RetrieveUpdateAPIView):
    """
    Retrieve and update the authenticated user's profile.
    """

    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user