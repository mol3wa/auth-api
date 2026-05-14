from django.urls import path
from . import views

urlpatterns = [
    path('signup/', views.SignupView.as_view(), name='signup'),
    path('verify-email/', views.VerifyEmailView.as_view(), name='verify-email'),
    path('login/', views.LoginView.as_view(), name='login'),
    path('update-email/', views.InitiateEmailUpdateView.as_view(), name='initiate-email-update'),
    path('verify-update-email/', views.VerifyEmailUpdateView.as_view(), name='verify-email-update'),
    path('delete-account/', views.DeleteAccountView.as_view(), name='delete-account'),
]

