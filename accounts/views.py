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
    serializer_class = SignupSerializer
    permission_classes = [permissions.AllowAny]

    def perform_create(self, serializer):
        user = serializer.save()
        otp = EmailOTP.generate_otp(user, 'signup')
        #send_otp_email(user.email, user.first_name, otp.otp_code, 'signup')

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(
            {"detail": "Signup successful. Please verify your email with the OTP sent."},
            status=status.HTTP_201_CREATED
        )

class VerifyEmailView(APIView):
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
    serializer_class = EmailTokenObtainPairSerializer

class InitiateEmailUpdateView(APIView):
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