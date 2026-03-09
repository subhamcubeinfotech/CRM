"""
Management command to create sample data for testing
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
import random

from apps.accounts.models import Company, CustomUser
from apps.shipments.models import Shipment, Container, ShipmentMilestone, Document
from apps.invoicing.models import Invoice, InvoiceLineItem, Payment
from apps.inventory.models import Warehouse, InventoryItem


class Command(BaseCommand):
    help = 'Create sample data for testing'

    def handle(self, *args, **kwargs):
        self.stdout.write('Creating sample data...')
        
        # Create companies
        self.create_companies()
        
        # Create users
        self.create_users()
        
        # Create warehouses
        self.create_warehouses()
        
        # Create inventory items
        self.create_inventory_items()
        
        # Create shipments
        self.create_shipments()
        
        # Create invoices
        self.create_invoices()
        
        self.stdout.write(self.style.SUCCESS('Sample data created successfully!'))
    
    def create_companies(self):
        self.stdout.write('Creating companies...')
        
        # Customers
        customers = [
            {
                'name': 'ABC Logistics Inc.',
                'company_type': 'customer',
                'city': 'New York',
                'state': 'NY',
                'phone': '(555) 100-1000',
                'email': 'contact@abclogistics.com',
            },
            {
                'name': 'Global Trade Solutions',
                'company_type': 'customer',
                'city': 'Los Angeles',
                'state': 'CA',
                'phone': '(555) 200-2000',
                'email': 'info@globaltrade.com',
            },
            {
                'name': 'FastShip Express',
                'company_type': 'customer',
                'city': 'Chicago',
                'state': 'IL',
                'phone': '(555) 300-3000',
                'email': 'support@fastship.com',
            },
            {
                'name': 'Pacific Imports LLC',
                'company_type': 'customer',
                'city': 'Seattle',
                'state': 'WA',
                'phone': '(555) 400-4000',
                'email': 'orders@pacificimports.com',
            },
            {
                'name': 'Atlantic Distribution',
                'company_type': 'customer',
                'city': 'Miami',
                'state': 'FL',
                'phone': '(555) 500-5000',
                'email': 'sales@atlanticdist.com',
            },
        ]
        
        # Carriers
        carriers = [
            {
                'name': 'Ocean Freight Lines',
                'company_type': 'carrier',
                'city': 'Houston',
                'state': 'TX',
                'phone': '(555) 600-6000',
                'email': 'bookings@oceanfreight.com',
            },
            {
                'name': 'FedEx Freight',
                'company_type': 'carrier',
                'city': 'Memphis',
                'state': 'TN',
                'phone': '(555) 700-7000',
                'email': 'freight@fedex.com',
            },
            {
                'name': 'UPS Freight Services',
                'company_type': 'carrier',
                'city': 'Atlanta',
                'state': 'GA',
                'phone': '(555) 800-8000',
                'email': 'freight@ups.com',
            },
        ]
        
        # Vendors
        vendors = [
            {
                'name': 'Packaging Supplies Co.',
                'company_type': 'vendor',
                'city': 'Denver',
                'state': 'CO',
                'phone': '(555) 900-9000',
                'email': 'orders@packagingsupplies.com',
            },
            {
                'name': 'Insurance Partners Inc.',
                'company_type': 'vendor',
                'city': 'Boston',
                'state': 'MA',
                'phone': '(555) 111-1111',
                'email': 'claims@insurancepartners.com',
            },
        ]
        
        all_companies = customers + carriers + vendors
        
        for data in all_companies:
            Company.objects.get_or_create(
                name=data['name'],
                defaults={
                    'company_type': data['company_type'],
                    'address_line1': f"123 {data['city']} Street",
                    'city': data['city'],
                    'state': data['state'],
                    'postal_code': f"{random.randint(10000, 99999)}",
                    'country': 'USA',
                    'phone': data['phone'],
                    'email': data['email'],
                    'payment_terms': random.choice([15, 30, 45, 60]),
                    'credit_limit': Decimal(random.randint(50000, 500000)),
                }
            )
        
        self.stdout.write(f'  Created {len(all_companies)} companies')
    
    def create_users(self):
        self.stdout.write('Creating users...')
        
        # Admin user
        admin_user, created = CustomUser.objects.get_or_create(
            username='admin',
            defaults={
                'email': 'admin@freightpro.com',
                'role': 'admin',
                'is_staff': True,
                'is_superuser': True,
            }
        )
        if created:
            admin_user.set_password('admin123')
            admin_user.save()
        
        # Customer users
        customers = Company.objects.filter(company_type='customer')[:3]
        for i, customer in enumerate(customers):
            user, created = CustomUser.objects.get_or_create(
                username=f'customer{i+1}',
                defaults={
                    'email': f'user{i+1}@{customer.name.lower().replace(" ", "")}.com',
                    'role': 'customer',
                    'company': customer,
                }
            )
            if created:
                user.set_password('customer123')
                user.save()
        
        # Staff users
        staff_data = [
            {'username': 'sales1', 'role': 'sales', 'email': 'sales@freightpro.com'},
            {'username': 'warehouse1', 'role': 'warehouse', 'email': 'warehouse@freightpro.com'},
        ]
        
        for data in staff_data:
            user, created = CustomUser.objects.get_or_create(
                username=data['username'],
                defaults={
                    'email': data['email'],
                    'role': data['role'],
                }
            )
            if created:
                user.set_password('staff123')
                user.save()
        
        self.stdout.write('  Created admin, customer, and staff users')
    
    def create_warehouses(self):
        self.stdout.write('Creating warehouses...')
        
        warehouses = [
            {'name': 'Chicago Main Warehouse', 'code': 'CHI-01', 'city': 'Chicago', 'state': 'IL'},
            {'name': 'Los Angeles Distribution', 'code': 'LA-01', 'city': 'Los Angeles', 'state': 'CA'},
            {'name': 'New York Storage Facility', 'code': 'NYC-01', 'city': 'New York', 'state': 'NY'},
        ]
        
        for data in warehouses:
            Warehouse.objects.get_or_create(
                code=data['code'],
                defaults={
                    'name': data['name'],
                    'address': f"100 {data['city']} Industrial Blvd",
                    'city': data['city'],
                    'state': data['state'],
                    'postal_code': f"{random.randint(10000, 99999)}",
                    'country': 'USA',
                    'phone': f'(555) {random.randint(100, 999)}-{random.randint(1000, 9999)}',
                }
            )
        
        self.stdout.write(f'  Created {len(warehouses)} warehouses')
    
    def create_inventory_items(self):
        self.stdout.write('Creating inventory items...')
        
        warehouses = list(Warehouse.objects.all())
        
        items = [
            {'sku': 'PKG-BOX-001', 'name': 'Standard Shipping Box', 'uom': 'pcs'},
            {'sku': 'PKG-TAPE-001', 'name': 'Packing Tape', 'uom': 'rolls'},
            {'sku': 'PKG-FOAM-001', 'name': 'Foam Padding', 'uom': 'sheets'},
            {'sku': 'PKG-PALLET-001', 'name': 'Wooden Pallet', 'uom': 'pcs'},
            {'sku': 'PKG-WRAP-001', 'name': 'Stretch Wrap', 'uom': 'rolls'},
        ]
        
        for data in items:
            InventoryItem.objects.get_or_create(
                sku=data['sku'],
                defaults={
                    'product_name': data['name'],
                    'description': f'Standard {data["name"].lower()} for shipping',
                    'warehouse': random.choice(warehouses),
                    'quantity': random.randint(50, 500),
                    'unit_of_measure': data['uom'],
                    'unit_cost': Decimal(random.randint(5, 100)),
                    'reorder_level': random.randint(20, 50),
                }
            )
        
        self.stdout.write(f'  Created {len(items)} inventory items')
    
    def create_shipments(self):
        self.stdout.write('Creating shipments...')
        
        customers = list(Company.objects.filter(company_type='customer'))
        carriers = list(Company.objects.filter(company_type='carrier'))
        
        cities = [
            ('New York', 'NY', 40.7128, -74.0060),
            ('Los Angeles', 'CA', 34.0522, -118.2437),
            ('Chicago', 'IL', 41.8781, -87.6298),
            ('Houston', 'TX', 29.7604, -95.3698),
            ('Phoenix', 'AZ', 33.4484, -112.0740),
            ('Philadelphia', 'PA', 39.9526, -75.1652),
            ('San Antonio', 'TX', 29.4241, -98.4936),
            ('San Diego', 'CA', 32.7157, -117.1611),
            ('Dallas', 'TX', 32.7767, -96.7970),
            ('San Jose', 'CA', 37.3382, -121.8863),
        ]
        
        shipment_types = ['ocean', 'air', 'road', 'rail']
        statuses = ['draft', 'booked', 'picked_up', 'in_transit', 'customs', 'out_for_delivery', 'delivered', 'cancelled']
        status_weights = [5, 10, 15, 25, 10, 10, 23, 2]
        
        for i in range(25):
            customer = random.choice(customers)
            carrier = random.choice(carriers) if random.random() > 0.3 else None
            
            origin_city = random.choice(cities)
            dest_city = random.choice([c for c in cities if c != origin_city])
            
            shipment_type = random.choice(shipment_types)
            status = random.choices(statuses, weights=status_weights)[0]
            
            pickup_date = timezone.now().date() - timedelta(days=random.randint(1, 30))
            est_delivery = pickup_date + timedelta(days=random.randint(3, 14))
            actual_delivery = est_delivery + timedelta(days=random.randint(-2, 3)) if status == 'delivered' else None
            
            weight = Decimal(random.randint(100, 10000))
            volume = Decimal(random.uniform(0.5, 50)).quantize(Decimal('0.01'))
            cost = Decimal(random.randint(500, 5000))
            revenue = cost * Decimal(random.uniform(1.2, 1.5))
            
            shipment = Shipment.objects.create(
                customer=customer,
                carrier=carrier,
                shipper=customer,
                shipment_type=shipment_type,
                status=status,
                tracking_number=f'TRK{random.randint(100000, 999999)}' if random.random() > 0.3 else '',
                origin_city=origin_city[0],
                origin_state=origin_city[1],
                origin_latitude=origin_city[2],
                origin_longitude=origin_city[3],
                destination_city=dest_city[0],
                destination_state=dest_city[1],
                destination_latitude=dest_city[2],
                destination_longitude=dest_city[3],
                pickup_date=pickup_date,
                estimated_delivery_date=est_delivery,
                actual_delivery_date=actual_delivery,
                total_weight=weight,
                total_volume=volume,
                number_of_pieces=random.randint(1, 20),
                commodity_description=f'General freight - {random.choice(["electronics", "machinery", "textiles", "food products", "automotive parts"])}',
                is_hazmat=random.random() < 0.1,
                is_temperature_controlled=random.random() < 0.15,
                requires_insurance=random.random() < 0.2,
                cost=cost,
                revenue=revenue.quantize(Decimal('0.01')),
                special_instructions='Handle with care' if random.random() > 0.7 else '',
                internal_notes='' if random.random() > 0.5 else 'Priority customer',
                created_by=CustomUser.objects.filter(role='admin').first(),
            )
            
            # Create milestones
            milestone_statuses = ['Shipment Created', 'Booked', 'Picked Up', 'In Transit', 'At Destination', 'Delivered']
            num_milestones = statuses.index(status) + 1 if status in statuses else 1
            
            for j in range(min(num_milestones, len(milestone_statuses))):
                ShipmentMilestone.objects.create(
                    shipment=shipment,
                    status=milestone_statuses[j],
                    location=origin_city[0] if j == 0 else (dest_city[0] if j == len(milestone_statuses) - 1 else f'Location {j}'),
                    notes='',
                )
        
        self.stdout.write('  Created 25 shipments with milestones')
    
    def create_invoices(self):
        self.stdout.write('Creating invoices...')
        
        customers = list(Company.objects.filter(company_type='customer'))
        shipments = list(Shipment.objects.filter(status='delivered'))
        
        invoice_statuses = ['draft', 'sent', 'paid', 'overdue', 'cancelled']
        status_weights = [10, 20, 40, 25, 5]
        
        for i in range(15):
            customer = random.choice(customers)
            shipment = random.choice(shipments) if shipments and random.random() > 0.3 else None
            
            status = random.choices(invoice_statuses, weights=status_weights)[0]
            
            invoice_date = timezone.now().date() - timedelta(days=random.randint(1, 60))
            due_date = invoice_date + timedelta(days=customer.payment_terms)
            paid_date = due_date - timedelta(days=random.randint(1, 5)) if status == 'paid' else None
            
            subtotal = Decimal(random.randint(1000, 15000))
            tax_rate = Decimal(random.choice([0, 5, 8, 10]))
            tax_amount = subtotal * (tax_rate / 100)
            total = subtotal + tax_amount
            amount_paid = total if status == 'paid' else (total * Decimal(random.uniform(0, 0.5)) if status == 'overdue' else Decimal('0'))
            
            invoice = Invoice.objects.create(
                customer=customer,
                shipment=shipment,
                invoice_date=invoice_date,
                due_date=due_date,
                paid_date=paid_date,
                tax_rate=tax_rate,
                amount_paid=amount_paid,
                status=status,
                notes='' if random.random() > 0.7 else 'Please pay within terms',
                terms=f'Net {customer.payment_terms} days',
                created_by=CustomUser.objects.filter(role='admin').first(),
            )
            
            # Create line items
            num_items = random.randint(1, 4)
            for j in range(num_items):
                descriptions = [
                    'Freight charges',
                    'Fuel surcharge',
                    'Handling fee',
                    'Insurance',
                    'Customs clearance',
                    'Storage fee',
                ]
                InvoiceLineItem.objects.create(
                    invoice=invoice,
                    description=random.choice(descriptions),
                    quantity=random.randint(1, 5),
                    unit_price=Decimal(random.randint(100, 2000)),
                )
            
            # Recalculate totals
            invoice.save()
        
        self.stdout.write('  Created 15 invoices with line items')
