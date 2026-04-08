from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('shipments', '0018_shipmentcomment'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ShipmentCommission',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('commission_type', models.CharField(choices=[('fixed', 'Fixed'), ('gross_profit_pct', '% Gross Profit'), ('material_cost_pct', '% Material Cost'), ('material_sale_pct', '% Material Sale')], default='fixed', max_length=30)),
                ('percentage', models.DecimalField(blank=True, decimal_places=4, max_digits=8, null=True)),
                ('amount', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('paid_date', models.DateField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('representative', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('shipment', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='commissions', to='shipments.shipment')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]

