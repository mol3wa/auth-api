from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APITestCase

from .models import AuditRecord, CreditUsage, Project, Task, Workspace, WorkspaceMembership
from .services import use_credits


User = get_user_model()


class UseCreditsTransactionTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
          email="test@example.com",
          first_name="Test",
          last_name="User",
          password="password123",
)
      
        self.workspace = Workspace.objects.create(
            name="Test Workspace",
            credit_balance=100,
        )

        self.workspace.members.add(self.user)

    def test_credits_are_deducted_and_records_created(self):
        use_credits(
            workspace=self.workspace,
            user=self.user,
            amount=20,
        )

        self.workspace.refresh_from_db()

        self.assertEqual(self.workspace.credit_balance, 80)

        self.assertEqual(
            CreditUsage.objects.count(),
            1,
        )

        self.assertEqual(
            AuditRecord.objects.count(),
            1,
        )

    def test_transaction_rolls_back_on_failure(self):
        original_balance = self.workspace.credit_balance

        try:
            with self.assertRaises(Exception):
                self._failing_credit_operation()
        finally:
            self.workspace.refresh_from_db()

        self.assertEqual(
            self.workspace.credit_balance,
            original_balance,
        )

        self.assertEqual(
            CreditUsage.objects.count(),
            0,
        )

        self.assertEqual(
            AuditRecord.objects.count(),
            0,
        )

    def _failing_credit_operation(self):
        from django.db import transaction

        with transaction.atomic():
            self.workspace.credit_balance -= 20
            self.workspace.save()

            raise Exception("Intentional failure")

            CreditUsage.objects.create(
                workspace=self.workspace,
                user=self.user,
                credits_used=20,
            )

            AuditRecord.objects.create(
                workspace=self.workspace,
                user=self.user,
                action="20 credits deducted",
            )


class ProjectAndTaskCreationApiTest(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="owner@example.com",
            first_name="Project",
            last_name="Owner",
            password="password123",
        )
        self.workspace = Workspace.objects.create(
            name="Creation Workspace",
            credit_balance=10,
        )
        WorkspaceMembership.objects.create(
            user=self.user,
            workspace=self.workspace,
            role=WorkspaceMembership.RoleType.OWNER,
        )
        self.client.force_authenticate(user=self.user)

    def test_create_project_then_task(self):
        project_response = self.client.post(
            "/api/projects/",
            {
                "workspace": self.workspace.id,
                "name": "Launch Project",
                "description": "Project creation smoke test",
            },
            format="json",
        )

        self.assertEqual(project_response.status_code, 201)
        project = Project.objects.get(id=project_response.data["id"])
        self.assertEqual(project.created_by, self.user)

        task_response = self.client.post(
            "/api/tasks/",
            {
                "project": project.id,
                "title": "Create API task",
                "description": "Task creation smoke test",
            },
            format="json",
        )

        self.assertEqual(task_response.status_code, 201)
        task = Task.objects.get(id=task_response.data["id"])
        self.assertEqual(task.created_by, self.user)
        self.assertEqual(task.project, project)
        self.assertEqual(task.status, Task.StatusType.TODO)
        self.workspace.refresh_from_db()
        self.assertEqual(self.workspace.credit_balance, 5)