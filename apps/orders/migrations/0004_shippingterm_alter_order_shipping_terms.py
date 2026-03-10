# Fixed migration: correct order of operations to avoid NOT NULL and FK constraint errors
# Order: Create ShippingTerm → Make CharField nullable → Clear values → Convert to FK

import django.db.models.deletion
from django.db import migrations, models


def clear_shipping_terms(apps, schema_editor):
    """Clear old text values now that the column is nullable."""
    Order = apps.get_model('orders', 'Order')
    Order.objects.all().update(shipping_terms=None)


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0003_tag_alter_order_shipping_terms_remove_order_tags_and_more'),
    ]

    operations = [
        # Step 1: Create the ShippingTerm table first
        migrations.CreateModel(
            name='ShippingTerm',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True)),
                ('description', models.CharField(blank=True, max_length=255)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        # Step 2: Make the existing CharField nullable (so we can set values to NULL)
        migrations.AlterField(
            model_name='order',
            name='shipping_terms',
            field=models.CharField(max_length=100, blank=True, null=True),
        ),
        # Step 3: Now clear all the old text values to NULL via ORM (column is now nullable)
        migrations.RunPython(clear_shipping_terms, migrations.RunPython.noop),
        # Step 4: Finally convert to ForeignKey (all rows are now NULL, no constraint violations)
        migrations.AlterField(
            model_name='order',
            name='shipping_terms',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='orders',
                to='orders.shippingterm',
            ),
        ),
    ]
