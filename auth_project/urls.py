from django.contrib import admin
from django.urls import path, include

from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)

from rest_framework.response import Response
from rest_framework.decorators import api_view


@api_view(['GET'])
def home(request):
    return Response({
        "message": "Welcome to the Auth API",
        "documentation": {
            "swagger": "/api/docs/",
            "redoc": "/api/redoc/",
            "schema": "/api/schema/",
        },
        "endpoints": {
            "signup": "/api/signup",
            "verify_email": "/api/verify-email",
            "login": "/api/login",
            "update_email": "/api/update-email",
            "verify_update_email": "/api/verify-update-email",
            "delete_account": "/api/delete-account",
        }
    })


urlpatterns = [
    path('', home),

    path('admin/', admin.site.urls),

    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),

    path(
        'api/docs/',
        SpectacularSwaggerView.as_view(url_name='schema'),
        name='swagger-ui'
    ),

    path(
        'api/redoc/',
        SpectacularRedocView.as_view(url_name='schema'),
        name='redoc'
    ),

    path('api/', include('accounts.urls')),
]