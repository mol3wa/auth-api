from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_workspace_credit_balance_non_negative"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="task",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    status__in=[
                        "TODO",
                        "IN_PROGRESS",
                        "IN_REVIEW",
                        "APPROVED",
                        "REJECTED",
                        "CANCELLED",
                    ]
                ),
                name="valid_task_status",
            ),
        ),
    ]