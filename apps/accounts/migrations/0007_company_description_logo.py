# Generated manually for company branding fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_signupotp'),
    ]

    operations = [
        migrations.AddField(
            model_name='company',
            name='description',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='company',
            name='logo',
            field=models.ImageField(blank=True, null=True, upload_to='company_logos/'),
        ),
    ]
