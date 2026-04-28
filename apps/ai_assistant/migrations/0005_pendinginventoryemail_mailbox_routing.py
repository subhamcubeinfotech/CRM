from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0026_customuser_mailbox_fields'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('ai_assistant', '0004_enhancements_suite'),
    ]

    operations = [
        migrations.AddField(
            model_name='pendinginventoryemail',
            name='mailbox_user',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='owned_inbox_emails', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='pendinginventoryemail',
            name='recipient_email',
            field=models.EmailField(blank=True, max_length=254),
        ),
    ]
