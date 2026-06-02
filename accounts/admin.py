from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import OfficerProfile


class OfficerProfileInline(admin.StackedInline):
    model = OfficerProfile
    can_delete = False
    extra = 0


class UserAdmin(BaseUserAdmin):
    inlines = [OfficerProfileInline]
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 'is_active')
    list_filter = ('is_staff', 'is_active', 'groups')


admin.site.unregister(User)
admin.site.register(User, UserAdmin)


@admin.register(OfficerProfile)
class OfficerProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'employee_id', 'phone', 'is_active_officer', 'created_at')
    list_filter = ('is_active_officer',)
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'employee_id')
