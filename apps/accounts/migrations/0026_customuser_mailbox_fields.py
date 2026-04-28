from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0025_tenant_logo'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='imap_host',
            field=models.CharField(blank=True, default='imap.gmail.com', max_length=255),
        ),
        migrations.AddField(
            model_name='customuser',
            name='imap_password',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='customuser',
            name='imap_port',
            field=models.PositiveIntegerField(default=993),
        ),
        migrations.AddField(
            model_name='customuser',
            name='imap_use_ssl',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='customuser',
            name='imap_username',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='customuser',
            name='inbox_email',
            field=models.EmailField(blank=True, help_text='Mailbox address watched for this user.', max_length=254),
        ),
        migrations.AddField(
            model_name='customuser',
            name='inbox_is_active',
            field=models.BooleanField(default=False, help_text='Enable personal inbox ingestion for this user.'),
        ),
    ]
