from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_company_description_logo'),
    ]

    operations = [
        migrations.AddField(
            model_name='company',
            name='latitude',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='company',
            name='longitude',
            field=models.FloatField(blank=True, null=True),
        ),
    ]
