from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from .models import EmailOTP, Workspace, WorkspaceMembership,Task,Project

User = get_user_model()

class SignupSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])

    class Meta:
        model = User
        fields = ('email', 'first_name', 'last_name', 'password')

    def create(self, validated_data):
        user = User.objects.create_user(
            email=validated_data['email'],
            first_name=validated_data['first_name'],
            last_name=validated_data['last_name'],
            password=validated_data['password'],
            is_active=False,  # inactive until email verified
        )
        return user

class VerifyEmailSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=6)

class InitiateEmailUpdateSerializer(serializers.Serializer):
    new_email = serializers.EmailField()

    def validate_new_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("This email is already in use.")
        return value

class VerifyEmailUpdateSerializer(serializers.Serializer):
    otp = serializers.CharField(max_length=6)

class DeleteAccountSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True)

class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "is_email_verified",
        ]
        read_only_fields = ["id", "email", "is_email_verified"]

class WorkspaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Workspace
        fields = [
            "id",
            "name",
            "description",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "created_at",
            "updated_at",
        ] 


class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = [
            "id",
            "workspace",
            "name",
            "description",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "created_by",
            "created_at",
            "updated_at",
        ]
    def validate_workspace(self, workspace):
        user = self.context["request"].user

        if not WorkspaceMembership.objects.filter(
            workspace=workspace,
            user=user
        ).exists():
            raise serializers.ValidationError(
                "You are not a member of this workspace."
            )

        return workspace


class WorkspaceMembershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkspaceMembership
        fields = [
            "id",
            "user",
            "workspace",
            "role",
            "joined_at",
        ]
        read_only_fields = [
            "joined_at",  
        ]
    
    def validate(self, attrs):
        user = attrs["user"]
        workspace = attrs["workspace"]

        if WorkspaceMembership.objects.filter(
            user=user,
            workspace=workspace
        ).exists():
            raise serializers.ValidationError(
                "This user is already a member of the workspace."
            )

        return attrs 


# serializers.py

class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = [
            "id", "project", "title", "description",
            "assigned_to", "created_by", "status",
            "created_at", "updated_at",
        ]
        read_only_fields = ["created_by", "created_at", "updated_at", "status"]
        extra_kwargs = {
            "assigned_to": {"required": False, "allow_null": True},
        }

    def validate(self, attrs):
        user = self.context["request"].user
        project = attrs.get("project") or (self.instance.project if self.instance else None)

        if project is None:
            raise serializers.ValidationError({"project": "This field is required."})

        if not WorkspaceMembership.objects.filter(
            workspace=project.workspace,
            user=user
        ).exists():
            raise serializers.ValidationError(
                "You are not a member of this workspace."
            )

        assigned_to = attrs.get("assigned_to")
        if assigned_to:
            if not WorkspaceMembership.objects.filter(
                workspace=project.workspace,
                user=assigned_to
            ).exists():
                raise serializers.ValidationError(
                    "The assigned user is not a member of this workspace."
                )

        return attrs




class UseCreditsSerializer(serializers.Serializer):
    amount = serializers.IntegerField(min_value=1)
    