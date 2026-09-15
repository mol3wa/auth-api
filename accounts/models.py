
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.conf import settings


class UserManager(BaseUserManager):
    """Manager for custom User model where email is the unique identifier."""

    def create_user(self, email, first_name, last_name, password=None, **extra_fields):
        if not email:
            raise ValueError("The Email field must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, first_name=first_name, last_name=last_name, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, first_name, last_name, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(email, first_name, last_name, password, **extra_fields)


class User(AbstractUser):
    username = None
    email = models.EmailField(_("email address"), unique=True)
    first_name = models.CharField(_("first name"), max_length=150)
    last_name = models.CharField(_("last name"), max_length=150)
    is_email_verified = models.BooleanField(default=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    objects = UserManager()          # <--- use the custom manager

    def __str__(self):
        return self.email


class EmailOTP(models.Model):
    PURPOSE_CHOICES = (
        ("signup", "Signup"),
        ("email_update", "Email Update"),
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="otps")
    otp_code = models.CharField(max_length=6)
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES)
    new_email = models.EmailField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_verified = models.BooleanField(default=False)
    
    
    def is_expired(self):
        from django.utils import timezone
        from datetime import timedelta
        return timezone.now() > self.created_at + timedelta(minutes=10)

    @classmethod
    def generate_otp(cls, user, purpose, new_email=None):
        import random
        cls.objects.filter(user=user, purpose=purpose, is_verified=False).delete()
        code = f"{random.randint(100000, 999999)}"
        return cls.objects.create(
            user=user,
            otp_code=code,
            purpose=purpose,
            new_email=new_email,
        )

class Workspace (models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    members = models.ManyToManyField(
        User,
        through="WorkspaceMembership",
        related_name="workspaces"
    )
    credit_balance = models.PositiveIntegerField(default=0)
    
    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(credit_balance__gte=0),
                name="credit_balance_non_negative",
            ),
        ]


    def __str__(self):
        return self.name

class WorkspaceMembership(models.Model):
    class RoleType(models.TextChoices):
        OWNER = "OWNER", "Owner"
        MANAGER = "MANAGER", "Manager"
        MEMBER = "MEMBER", "Member"
    user= models.ForeignKey(User, on_delete=models.CASCADE,related_name="memberships")
    workspace= models.ForeignKey(Workspace, on_delete=models.CASCADE,related_name="memberships")
    role= models.CharField(choices=RoleType.choices, max_length=20)
    joined_at = models.DateTimeField(auto_now_add=True)
    class Meta:
     constraints = [
        models.UniqueConstraint(
            fields=["workspace", "user"],
            name="unique_workspace_membership"
        )
    ]
    def __str__(self):
        return f"{self.user.email} - {self.workspace.name} ({self.role})"

class CreditUsage(models.Model):
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="credit_usages",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="credit_usages",
    )
    credits_used = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.credits_used} credits used by {self.workspace.name}"

class AuditRecord(models.Model):
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="audit_records",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_records",
    )
    action = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.action} - {self.workspace.name}"



class Project(models.Model):
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="projects")
    name = models.CharField(max_length=255)
    created_by= models.ForeignKey(User,on_delete=models.CASCADE,
        related_name="created_projects" )
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class Task(models.Model):
    class StatusType(models.TextChoices):
        TODO = "TODO", "Todo"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        IN_REVIEW = "IN_REVIEW", "In Review"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        CANCELLED = "CANCELLED", "Cancelled"
    project = models.ForeignKey(Project, on_delete=models.CASCADE,
        related_name="tasks")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    assigned_to= models.ForeignKey(User,on_delete=models.SET_NULL,null=True, blank=True, related_name="assigned_tasks" )
    created_by= models.ForeignKey(User,on_delete=models.SET_NULL,null=True, related_name="created_tasks" )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    status= models.CharField(choices=StatusType.choices,max_length=20, default=StatusType.TODO)

    TRANSITIONS = {
        "start":   ({StatusType.TODO}, StatusType.IN_PROGRESS),
        "submit":  ({StatusType.IN_PROGRESS, StatusType.REJECTED}, StatusType.IN_REVIEW),
        "approve": ({StatusType.IN_REVIEW}, StatusType.APPROVED),
        "reject":  ({StatusType.IN_REVIEW}, StatusType.REJECTED),
        "cancel":  ({StatusType.TODO, StatusType.IN_PROGRESS, StatusType.IN_REVIEW}, StatusType.CANCELLED),
    }

    def can_transition(self, action_name):
        allowed_from, _ = self.TRANSITIONS[action_name]
        return self.status in allowed_from

    def apply_transition(self, action_name):
        _, target_status = self.TRANSITIONS[action_name]
        self.status = target_status
        self.save(update_fields=["status"])
    def __str__(self):
        return self.title
    
class Notification(models.Model):
    class NotificationType(models.TextChoices):
        WORKSPACE_INVITE = "workspace_invite", "Workspace Invite"
        TASK_ASSIGNED = "task_assigned", "Task Assigned"
        TASK_APPROVED = "task_approved", "Task Approved"
        WORKSPACE_CREATED = "workspace_created", "Workspace Created"

    class StatusType(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        SUCCESS = "SUCCESS", "Success"
        FAILED = "FAILED", "Failed"

    recipient = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="notifications"
    )
    notification_type = models.CharField(max_length=50, choices=NotificationType.choices)
    payload = models.JSONField(default=dict, blank=True)

    status = models.CharField(
        max_length=20, choices=StatusType.choices, default=StatusType.PENDING
    )
    attempts = models.PositiveIntegerField(default=0)
    last_error_message = models.TextField(blank=True, default="")
    sent_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self):
        return f"{self.notification_type} -> {self.recipient_id} ({self.status})"
 