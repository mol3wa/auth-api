from django.urls import path
from . import views
from .views import (
    UseCreditsView,
    WorkspaceViewSet,
    WorkspaceMembershipViewSet,
    ProjectViewSet,
    TaskViewSet,
    

)
from rest_framework.routers import DefaultRouter

urlpatterns = [
    path('signup/', views.SignupView.as_view(), name='signup'),
    path('verify-email/', views.VerifyEmailView.as_view(), name='verify-email'),
    path('login/', views.LoginView.as_view(), name='login'),
    path('update-email/', views.InitiateEmailUpdateView.as_view(), name='initiate-email-update'),
    path('verify-update-email/', views.VerifyEmailUpdateView.as_view(), name='verify-email-update'),
    path('delete-account/', views.DeleteAccountView.as_view(), name='delete-account'),
    path("profile/", views.UserProfileView.as_view(), name="user-profile"),
    path("api/workspaces/<int:workspace_id>/credits/use/",UseCreditsView.as_view(),name="use-credits"),
]
router = DefaultRouter()

router.register(r"workspaces", WorkspaceViewSet, basename="workspace")
router.register(r"memberships", WorkspaceMembershipViewSet, basename="membership")
router.register(r"projects", ProjectViewSet, basename="project")
router.register(r"tasks", TaskViewSet, basename="task")

urlpatterns += router.urls

