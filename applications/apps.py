from django.apps import AppConfig


class ApplicationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'applications'
    verbose_name = 'Application Processing'

    def ready(self):
        import applications.checks  # noqa: F401
        import applications.signals  # noqa: F401
