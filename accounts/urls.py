from django.urls import path

from .views import OfficerLoginView, OfficerLogoutView

app_name = 'accounts'

urlpatterns = [
    path('login/', OfficerLoginView.as_view(), name='login'),
    path('logout/', OfficerLogoutView.as_view(), name='logout'),
]
