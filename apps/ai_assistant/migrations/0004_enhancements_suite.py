# Generated manually due local dependency constraints.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0016_teaminvitation'),
        ('inventory', '0021_inventoryitem_image'),
        ('orders', '0014_alter_manifestitem_buy_price_and_more'),
        ('shipments', '0020_alter_container_weight_alter_shipment_cost_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('ai_assistant', '0003_pendinginventoryemail_message_id_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='pendinginventoryemail',
            name='priority_level',
            field=models.CharField(default='medium', max_length=20),
        ),
        migrations.AddField(
            model_name='pendinginventoryemail',
            name='sentiment_label',
            field=models.CharField(default='neutral', max_length=20),
        ),
        migrations.AddField(
            model_name='pendinginventoryemail',
            name='sentiment_reason',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='pendinginventoryemail',
            name='sentiment_score',
            field=models.FloatField(default=0.0, help_text='-1.0 (negative) to +1.0 (positive)'),
        ),
        migrations.CreateModel(
            name='DemandForecastSnapshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('current_quantity', models.DecimalField(decimal_places=2, default=0, max_digits=20)),
                ('avg_daily_usage', models.DecimalField(decimal_places=4, default=0, max_digits=20)),
                ('days_to_runout', models.IntegerField(blank=True, null=True)),
                ('predicted_runout_date', models.DateField(blank=True, null=True)),
                ('confidence_score', models.FloatField(default=0.0)),
                ('alert_level', models.CharField(choices=[('healthy', 'Healthy'), ('watch', 'Watch'), ('risk', 'Risk'), ('critical', 'Critical')], default='healthy', max_length=20)),
                ('notes', models.TextField(blank=True)),
                ('computed_at', models.DateTimeField(auto_now=True)),
                ('tenant', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='%(app_label)s_%(class)s_related', to='accounts.tenant')),
                ('inventory_item', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='forecast_snapshots', to='inventory.inventoryitem')),
            ],
            options={
                'ordering': ['days_to_runout', '-computed_at'],
                'unique_together': {('tenant', 'inventory_item')},
            },
        ),
        migrations.CreateModel(
            name='DocumentVisionRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_type', models.CharField(choices=[('general', 'General Upload'), ('shipment', 'Shipment Document'), ('order', 'Order Document'), ('company', 'Company Document')], default='general', max_length=20)),
                ('uploaded_file', models.FileField(blank=True, null=True, upload_to='ai_vision/%Y/%m/')),
                ('extracted_text', models.TextField(blank=True)),
                ('extracted_json', models.JSONField(blank=True, default=dict)),
                ('confidence_score', models.FloatField(default=0.0)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('completed', 'Completed'), ('failed', 'Failed')], default='pending', max_length=20)),
                ('error_message', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('company_document', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='vision_records', to='accounts.companydocument')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='vision_records', to=settings.AUTH_USER_MODEL)),
                ('order_document', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='vision_records', to='orders.orderdocument')),
                ('shipment_document', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='vision_records', to='shipments.document')),
                ('tenant', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='%(app_label)s_%(class)s_related', to='accounts.tenant')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='QuoteDraft',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quantity', models.DecimalField(decimal_places=2, default=0, max_digits=20)),
                ('unit', models.CharField(default='lbs', max_length=30)),
                ('supplier_unit_price', models.DecimalField(decimal_places=4, default=0, max_digits=20)),
                ('markup_percent', models.DecimalField(decimal_places=2, default=0, max_digits=8)),
                ('quoted_unit_price', models.DecimalField(decimal_places=4, default=0, max_digits=20)),
                ('total_amount', models.DecimalField(decimal_places=2, default=0, max_digits=20)),
                ('currency', models.CharField(default='USD', max_length=10)),
                ('subject', models.CharField(max_length=255)),
                ('body_text', models.TextField()),
                ('status', models.CharField(choices=[('draft', 'Draft'), ('sent', 'Sent'), ('approved', 'Approved'), ('rejected', 'Rejected')], default='draft', max_length=20)),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('buyer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='incoming_quote_drafts', to='accounts.company')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_quote_drafts', to=settings.AUTH_USER_MODEL)),
                ('inventory_item', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='quote_drafts', to='inventory.inventoryitem')),
                ('requirement', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='quote_drafts', to='ai_assistant.buyerrequirement')),
                ('smart_match', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='quote_drafts', to='ai_assistant.smartmatch')),
                ('supplier', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='outgoing_quote_drafts', to='accounts.company')),
                ('tenant', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='%(app_label)s_%(class)s_related', to='accounts.tenant')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
