from rest_framework import permissions
from .models import WorkspaceMembership, Workspace, Project, Task

def has_permission(self, request, view):
    if view.action != "create":
        return True

    
class BaseWorkspacePermission(permissions.BasePermission):

    def get_workspace(self, obj):
        if isinstance(obj, Workspace):
            return obj

        if isinstance(obj, Project):
            return obj.workspace

        if isinstance(obj, Task):
            return obj.project.workspace

        return None

    def get_membership(self, request, obj):
        workspace = self.get_workspace(obj)

        if workspace is None:
            return None

        return WorkspaceMembership.objects.filter(
            workspace=workspace,
            user=request.user
        ).first()

class IsWorkspaceOwner(BaseWorkspacePermission):

    def has_object_permission(self, request, view, obj):
        membership = self.get_membership(request, obj)

        if membership is None:
            return False

        return membership.role == WorkspaceMembership.RoleType.OWNER
  
class IsWorkspaceManagerOrOwner(BaseWorkspacePermission):
    """
    Owners and Managers only. Handles both:
    - creation (no object yet -> resolve workspace from payload)
    - update/destroy (object exists -> normal object permission check)
    """

    MANAGE_ROLES = [
        WorkspaceMembership.RoleType.OWNER,
        WorkspaceMembership.RoleType.MANAGER,
    ]

    def _membership_for_workspace(self, request, workspace_id):
        if not workspace_id:
            return None
        return WorkspaceMembership.objects.filter(
            workspace_id=workspace_id,
            user=request.user,
        ).first()

    def has_permission(self, request, view):
        # Only pre-check on create. Update/destroy are gated by
        # has_object_permission once DRF has the actual object.
        if view.action != "create":
            return True

        if view.basename == "project":
            membership = self._membership_for_workspace(
                request, request.data.get("workspace")
            )

        elif view.basename == "task":
            project = Project.objects.filter(
                id=request.data.get("project")
            ).first()
            if project is None:
                return False
            membership = self._membership_for_workspace(
                request, project.workspace_id
            )

        else:
            return True

        return membership is not None and membership.role in self.MANAGE_ROLES

    def has_object_permission(self, request, view, obj):
        membership = self.get_membership(request, obj)
        return membership is not None and membership.role in self.MANAGE_ROLES


    
class IsWorkspaceMember(BaseWorkspacePermission):

    def has_object_permission(self, request, view, obj):
        return self.get_membership(request, obj) is not None

class IsAssignedUser(permissions.BasePermission):

    def has_object_permission(self, request, view, obj):
        return obj.assigned_to == request.user