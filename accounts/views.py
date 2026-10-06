from django.http import request
from rest_framework import status, generics, permissions,viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model
from rest_framework.views import APIView

from accounts.permissions import IsAssignedUser, IsWorkspaceManagerOrOwner, IsWorkspaceOwner
from .models import Workspace,WorkspaceMembership,Task,Project

from .serializers import (
    SignupSerializer, VerifyEmailSerializer,
    InitiateEmailUpdateSerializer, VerifyEmailUpdateSerializer,
    DeleteAccountSerializer, UserProfileSerializer, WorkspaceSerializer,WorkspaceMembershipSerializer,ProjectSerializer,TaskSerializer,UseCreditsSerializer
)
from .services import (
    signup_user,
    verify_signup_otp,
    initiate_email_update,
    verify_email_update,
    delete_user_account,
    WorkspaceService,
    ProjectService,
    TaskService,
    use_credits_idempotently

)
from drf_spectacular.utils import extend_schema
from drf_spectacular.types import OpenApiTypes
from rest_framework.decorators import action
import hashlib

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from .models import IdempotencyKey, Workspace

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


class WorkspaceViewSet(viewsets.ModelViewSet):
    serializer_class = WorkspaceSerializer

    def get_queryset(self):
        return Workspace.objects.filter(
            memberships__user=self.request.user
        ).distinct()

    def perform_create(self, serializer):
        workspace = WorkspaceService.create_workspace(
            user=self.request.user,
            validated_data=serializer.validated_data,
        )
        serializer.instance = workspace

    def get_permissions(self):
        if self.action == "destroy":
            return [permissions.IsAuthenticated(), IsWorkspaceOwner()]
        return [permissions.IsAuthenticated()]


class WorkspaceMembershipViewSet(viewsets.ModelViewSet):
    serializer_class = WorkspaceMembershipSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return WorkspaceMembership.objects.filter(user=self.request.user)
    
    def perform_create(self, serializer):
        membership = WorkspaceService.add_member(
            invited_by=self.request.user,
            validated_data=serializer.validated_data,
        )
        serializer.instance = membership


class ProjectViewSet(viewsets.ModelViewSet):
    serializer_class = ProjectSerializer

    def get_queryset(self):
        return Project.objects.filter(
            workspace__memberships__user=self.request.user
        ).distinct()

    def perform_create(self, serializer):
        project = ProjectService.create_project(
            user=self.request.user,
            validated_data=serializer.validated_data,
        )
        serializer.instance = project

    def get_permissions(self):
        if self.action in ["create", "update", "partial_update", "destroy"]:
            return [permissions.IsAuthenticated(), IsWorkspaceManagerOrOwner()]
        return [permissions.IsAuthenticated()]


class TaskViewSet(viewsets.ModelViewSet):
    serializer_class = TaskSerializer

    def get_queryset(self):
        return Task.objects.filter(
            project__workspace__memberships__user=self.request.user
        ).distinct()

    def perform_create(self, serializer):
        task = TaskService.create_task(
            user=self.request.user,
            validated_data=serializer.validated_data,
        )
        serializer.instance = task

    def get_permissions(self):
        if self.action == "create":
            return [permissions.IsAuthenticated(), IsWorkspaceManagerOrOwner()]

        if self.action in ["update", "partial_update", "start"]:
            return [
                permissions.IsAuthenticated(),
                (IsWorkspaceManagerOrOwner | IsAssignedUser)(),
            ]

        if self.action == "submit":
            return [permissions.IsAuthenticated(), IsAssignedUser()]

        if self.action in ["approve", "reject", "cancel"]:
            return [permissions.IsAuthenticated(), IsWorkspaceManagerOrOwner()]

        return [permissions.IsAuthenticated()]

    # --- custom actions: just fetch object -> call service -> serialize ---
    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        task = TaskService.transition(self.get_object(), "start", request.user)
        return Response(self.get_serializer(task).data)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        task = TaskService.transition(self.get_object(), "submit", request.user)
        return Response(self.get_serializer(task).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        task = TaskService.transition(self.get_object(), "approve", request.user)
        return Response(self.get_serializer(task).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        task = TaskService.transition(self.get_object(), "reject", request.user)
        return Response(self.get_serializer(task).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        task = TaskService.transition(self.get_object(), "cancel", request.user)
        return Response(self.get_serializer(task).data)


class UseCreditsView(APIView):
    serializer_class = UseCreditsSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request, workspace_id):
        workspace = get_object_or_404(
            Workspace,
            pk=workspace_id,
        )

        serializer = self.serializer_class(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        idempotency_key = request.headers.get(
            "Idempotency-Key"
        )

        if not idempotency_key:
            return Response(
                {
                    "detail": "Idempotency-Key header is required."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        amount = serializer.validated_data["amount"]

        try:
            result = use_credits_idempotently(
                workspace=workspace,
                user=request.user,
                amount=amount,
                idempotency_key=idempotency_key,
            )

        except ValueError as error:
            return Response(
                {"detail": str(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            result,
            status=status.HTTP_200_OK,
        )