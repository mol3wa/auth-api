from rest_framework import status, generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from django.contrib.auth import get_user_model
from .serializers import (
    SignupSerializer, VerifyEmailSerializer,
    InitiateEmailUpdateSerializer, VerifyEmailUpdateSerializer,
    DeleteAccountSerializer
)
from .models import EmailOTP
from .services import send_otp_email

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
        user = serializer.save()
        otp = EmailOTP.generate_otp(user, 'signup')
        send_otp_email(user.email, user.first_name, otp.otp_code, 'signup')

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(
            {"detail": "Signup successful. Please verify your email with the OTP sent."},
            status=status.HTTP_201_CREATED
        )

class VerifyEmailView(APIView):
    """
    Verify a user's email using the OTP they received.

    Required fields: `email` (the address used during signup) and `otp` (6‑digit code).
    On success the account is activated and can log in.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = VerifyEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']
        otp_code = serializer.validated_data['otp']
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"detail": "Invalid email."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            otp = EmailOTP.objects.get(user=user, purpose='signup', is_verified=False)
        except EmailOTP.DoesNotExist:
            return Response({"detail": "No OTP found or already verified."}, status=status.HTTP_400_BAD_REQUEST)

        if otp.is_expired():
            otp.delete()
            return Response({"detail": "OTP expired. Please sign up again."}, status=status.HTTP_400_BAD_REQUEST)

        if otp.otp_code != otp_code:
            return Response({"detail": "Invalid OTP."}, status=status.HTTP_400_BAD_REQUEST)

        otp.is_verified = True
        otp.save()
        user.is_active = True
        user.is_email_verified = True
        user.save()
        return Response({"detail": "Email verified successfully. You can now login."}, status=status.HTTP_200_OK)

# Custom login using email
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
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

class InitiateEmailUpdateView(APIView):
    """
    Request to change the authenticated user's email address.

    Requires a valid JWT token in the `Authorization` header.
    Send `{"new_email": "new@example.com"}`. A new OTP is sent to the new address.
    Complete the update by verifying that OTP via `/api/verify-update-email/`.
    """


    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = InitiateEmailUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_email = serializer.validated_data['new_email']
        user = request.user
        otp = EmailOTP.generate_otp(user, 'email_update', new_email=new_email)
        send_otp_email(new_email, user.first_name, otp.otp_code, 'email_update')
        return Response({"detail": "OTP sent to new email. Verify to complete update."})

class VerifyEmailUpdateView(APIView):
    """
    Confirm an email change by submitting the OTP sent to the new address.

    Requires a valid JWT token. Send `{"otp": "123456"}`.
    On success the user's email is permanently updated to the new address.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = VerifyEmailUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        otp_code = serializer.validated_data['otp']
        user = request.user

        try:
            otp = EmailOTP.objects.get(user=user, purpose='email_update', is_verified=False)
        except EmailOTP.DoesNotExist:
            return Response({"detail": "No pending email update OTP."}, status=status.HTTP_400_BAD_REQUEST)

        if otp.is_expired():
            otp.delete()
            return Response({"detail": "OTP expired. Please request a new one."}, status=status.HTTP_400_BAD_REQUEST)

        if otp.otp_code != otp_code:
            return Response({"detail": "Invalid OTP."}, status=status.HTTP_400_BAD_REQUEST)

        # Update email
        user.email = otp.new_email
        user.save()
        otp.is_verified = True
        otp.save()
        return Response({"detail": "Email updated successfully."})

class DeleteAccountView(APIView):
    """
    Permanently delete the authenticated user's account.

    Requires a valid JWT token. The request body must contain the current `password`.
    If the password is correct the account is removed immediately.
    """
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request):
        serializer = DeleteAccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        password = serializer.validated_data['password']
        user = request.user
        if not user.check_password(password):
            return Response({"detail": "Incorrect password."}, status=status.HTTP_400_BAD_REQUEST)
        user.delete()
        return Response({"detail": "Account deleted."}, status=status.HTTP_204_NO_CONTENT)