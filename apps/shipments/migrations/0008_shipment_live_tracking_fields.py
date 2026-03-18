# Generated manually for live tracking support

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shipments', '0007_alter_shipment_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='shipment',
            name='driver_name',
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name='shipment',
            name='driver_phone',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name='shipment',
            name='last_location_text',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='shipment',
            name='last_location_updated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='shipment',
            name='tracking_active',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='shipment',
            name='vehicle_number',
            field=models.CharField(blank=True, max_length=50),
        ),
    ]
