from django.contrib import admin

from .models import ActivityLog


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'user', 'action', 'model_name', 'object_id', 'ip_address')
    list_filter = ('action', 'model_name')
    search_fields = ('description', 'object_id', 'user__username')
    readonly_fields = ('timestamp',)
