# Freight Forwarding & Logistics Management Platform

A comprehensive freight forwarding and logistics management platform built with Django. This professional business application is designed for freight brokers and logistics companies to manage shipments, invoices, inventory, and customer relationships.

## Features

### Core Modules

1. **Dashboard** - Main control center with key metrics, charts, and recent shipments
2. **Shipment Management** - Full CRUD operations with tracking, documents, and milestones
3. **Customer Portal** - Self-service portal for customers to track shipments and view invoices
4. **Invoice Management** - Create, manage, and track invoices with payment history
5. **Bill of Lading Generator** - Auto-generate professional BOL documents
6. **Rate Comparison & Profit Calculator** - Compare carrier rates and calculate profit margins
7. **Inventory Management** - Track warehouse inventory and stock levels
8. **Company Management** - Manage customers, carriers, and vendors

### Key Features

- **Interactive Maps** - Leaflet.js integration for shipment tracking visualization
- **Charts & Analytics** - Chart.js for revenue trends and shipment status distribution
- **Role-Based Access** - Different access levels for admin, customer, driver, warehouse, and sales
- **Document Management** - Upload and download shipment documents
- **Real-Time Calculations** - Live profit margin calculations in the rate comparison tool
- **Responsive Design** - Bootstrap 5.3 for mobile-friendly interface

## Technology Stack

### Backend
- **Framework**: Django 5.0+
- **Database**: SQLite (development) / PostgreSQL (production)
- **API**: Django REST Framework
- **Authentication**: Django built-in auth with role-based access

### Frontend
- **Base**: HTML5, CSS3, JavaScript (ES6+)
- **CSS Framework**: Bootstrap 5.3
- **Icons**: Font Awesome 6
- **Charts**: Chart.js
- **Maps**: Leaflet.js

### Additional Libraries
- **PDF Generation**: ReportLab (Python)
- **Excel Export**: openpyxl (Python)
- **Barcode Generation**: python-barcode
- **Date Handling**: python-dateutil

## Installation

### Prerequisites
- Python 3.10+
- pip

### Setup Steps

1. **Clone the repository**
   ```bash
   cd freight_platform
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run migrations**
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   ```

4. **Create superuser**
   ```bash
   python manage.py createsuperuser
   ```

5. **Load sample data (optional)**
   ```bash
   python manage.py create_sample_data
   ```

6. **Run the development server**
   ```bash
   python manage.py runserver
   ```

7. **Access the application**
   - Main App: http://127.0.0.1:8000/
   - Admin Panel: http://127.0.0.1:8000/admin/

## Default Credentials

After running `create_sample_data`, the following accounts are available:

| Username | Password | Role |
|----------|----------|------|
| admin | admin123 | Administrator |
| customer1 | customer123 | Customer |
| customer2 | customer123 | Customer |
| customer3 | customer123 | Customer |
| sales1 | staff123 | Sales |
| warehouse1 | staff123 | Warehouse |

## URL Structure

| URL | Description |
|-----|-------------|
| `/` or `/dashboard/` | Main dashboard |
| `/login/` | Login page |
| `/logout/` | Logout |
| `/shipments/` | Shipment list |
| `/shipments/create/` | Create shipment |
| `/shipments/<id>/` | Shipment detail with tracking |
| `/shipments/<id>/edit/` | Edit shipment |
| `/shipments/<id>/bol/` | Generate Bill of Lading |
| `/portal/` | Customer portal |
| `/invoices/` | Invoice list |
| `/invoices/pending/` | Pending invoices |
| `/invoices/<id>/` | Invoice detail |
| `/tools/rate-comparison/` | Rate comparison & profit calculator |
| `/inventory/` | Inventory dashboard |
| `/companies/` | Company list |
| `/admin/` | Django admin panel |

## Database Models

### Accounts
- **CustomUser** - Extended user model with roles
- **Company** - Customers, carriers, and vendors

### Shipments
- **Shipment** - Core shipment model
- **Container** - Container details for ocean/rail
- **ShipmentMilestone** - Tracking timeline
- **Document** - Shipment documents

### Invoicing
- **Invoice** - Invoice management
- **InvoiceLineItem** - Invoice line items
- **Payment** - Payment records

### Inventory
- **Warehouse** - Warehouse locations
- **InventoryItem** - Inventory tracking

### Tools
- **RateQuote** - Rate comparison quotes

## Screenshots

### Dashboard
The dashboard provides an overview of key metrics including:
- Active shipments count
- Monthly revenue
- Pending invoices
- On-time delivery rate
- Revenue trend chart
- Shipment status distribution

### Shipment Detail
Detailed view with:
- Interactive map with origin, current location, and destination
- Shipment timeline with progress
- Document management
- Financial details
- Container information

### Rate Comparison Tool
Three-column layout:
1. **Input Form** - Enter shipment details
2. **Rate Results** - Compare carrier rates
3. **Profit Calculator** - Real-time profit calculation

## Development

### Running Tests
```bash
python manage.py test
```

### Creating Migrations
```bash
python manage.py makemigrations
python manage.py migrate
```

### Admin Panel
Access the Django admin panel at `/admin/` to manage all models.

## Production Deployment

### Settings to Update
1. Change `SECRET_KEY` in `config/settings.py`
2. Set `DEBUG = False`
3. Update `ALLOWED_HOSTS`
4. Configure PostgreSQL database
5. Set up static files with WhiteNoise or CDN
6. Configure email backend

### Environment Variables
```bash
export DJANGO_SECRET_KEY='your-secret-key'
export DJANGO_DEBUG=False
export DJANGO_ALLOWED_HOSTS='your-domain.com'
```

## License

This project is licensed under the MIT License.

## Support

For support, please contact support@freightpro.com or open an issue in the repository.
