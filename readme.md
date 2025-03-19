# Django Integer to UUID Primary Key Migration

This utility helps you seamlessly convert Django models from integer primary keys to UUID primary keys while preserving all relationships and data integrity.

## Overview

Migrating from auto-incrementing integer primary keys to UUID in Django can be challenging, especially with complex relationships. This tool handles:

- Foreign key relationships
- Many-to-many relationships
- Custom primary key fields
- Cross-app relationships

## Quick Start

### 1. Install and Setup

Copy the `uuid_migration_utils.py` file to your Django app directory:

```bash
# Clone the repository
git clone https://github.com/yourusername/django-uuid-migration.git

# Copy the utility file to your app
cp django-uuid-migration/uuid_migration_utils.py yourproject/yourapp/
```

### 2. Check for M2M Relationships

Create an empty migration and use our utility to detect any issues:

```bash
python manage.py makemigrations --empty yourapp
```

Edit the migration file:

```python
from django.db import migrations
from yourapp.uuid_migration_utils import create_uuid_migration

Migration = create_uuid_migration(
    parent_model='YourModel',  # Model to convert
    app_name='yourapp',        # App name
    dependencies=[('yourapp', 'xxxx_previous_migration')],
    auto_detect_relations=True # Auto-detect relationships
)
```

If M2M relationships are detected, the script will provide detailed instructions.

### 3. Handle M2M Relationships (if needed)

If your model uses implicit M2M relationships:

1. Delete the migration file from step 2
2. Create through models as suggested in the error message
3. Create and edit migration files for M2M relationships using the provided templates
4. Apply these migrations: `python manage.py migrate`
5. Update your model classes to use the through models

Example M2M through model:

```python
class ProductCategoryThrough(models.Model):
    product = models.ForeignKey('Product', on_delete=models.CASCADE, db_index=True)
    category = models.ForeignKey('Category', on_delete=models.CASCADE, db_index=True)
    
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['product', 'category'], name='unique_product_category')
        ]
```

### 4. Run UUID Migration

After fixing all M2M relationships:

1. Create another empty migration:
   ```bash
   python manage.py makemigrations --empty yourapp
   ```

2. Use `create_uuid_migration` again:
   ```python
   from django.db import migrations
   from yourapp.uuid_migration_utils import create_uuid_migration

   Migration = create_uuid_migration(
       parent_model='YourModel',
       app_name='yourapp',
       dependencies=[('yourapp', 'xxxx_latest_migration')],
       auto_detect_relations=True
   )
   ```

3. Update your model class to use UUID:
   ```python
   import uuid
   from django.db import models

   class YourModel(models.Model):
       id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
       # other fields...
   ```

4. Make and apply migrations:
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   ```

## Core Features

- **Automatic Relationship Detection**: Finds all models that have a relationship with your target model
- **Data Preservation**: Maintains all existing data and relationships during migration
- **Comprehensive M2M Support**: Handles explicit through models and helps convert implicit M2M relationships
- **Cross-App Compatibility**: Works with relationships across different Django apps

## Advanced Usage

### Custom Primary Key Fields

For models with non-standard primary key field names:

```python
Migration = create_uuid_migration(
    parent_model='CustomModel',
    app_name='yourapp',
    dependencies=[('yourapp', 'xxxx_previous')],
    pk_field='custom_id',  # Specify custom PK field name
    auto_detect_relations=True
)
```

### Manual Relationship Specification

If you prefer to manually specify relationships:

```python
Migration = create_uuid_migration(
    parent_model='YourModel',
    app_name='yourapp',
    dependencies=[('yourapp', 'xxxx_previous')],
    child_models=[
        {'model': 'RelatedModel', 'fk_field': 'your_model', 'app_name': 'yourapp'},
        {'model': 'AnotherModel', 'fk_field': 'parent', 'app_name': 'another_app'}
    ],
    auto_detect_relations=False  # Disable auto-detection
)
```

## Common Issues

### M2M Relationship Migration Details

Django doesn't allow direct conversion from implicit to explicit M2M relationships. You must use `SeparateDatabaseAndState` as shown in the error messages produced by this tool.

The process requires:

1. Creating a through model
2. Creating a migration that:
   - Uses the existing M2M table (via `AlterModelTable`)
   - Updates Django's state (via `SeparateDatabaseAndState`)
   - Adds any additional fields to the table
3. Updating your models to use the through model

### Performance Considerations

- **Large Tables**: Migrations on tables with millions of rows may take significant time
- **Database Locks**: Consider running migrations during low-traffic periods
- **Backup**: Always create a database backup before running these migrations
- **Test First**: Test on a development environment before applying to production

## Complete Example

### Original Models
```python
class Category(models.Model):
    name = models.CharField(max_length=100)

class Product(models.Model):
    name = models.CharField(max_length=100)
    categories = models.ManyToManyField(Category)  # Implicit M2M
```

### Step 1: Fix M2M Relationship
```python
# New through model
class ProductCategoryRelation(models.Model):
    product = models.ForeignKey('Product', on_delete=models.CASCADE, db_index=True)
    category = models.ForeignKey('Category', on_delete=models.CASCADE, db_index=True)
    
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['product', 'category'], name='unique_product_category')
        ]

# Updated Product model
class Product(models.Model):
    name = models.CharField(max_length=100)
    categories = models.ManyToManyField(Category, through='ProductCategoryRelation')
```

### Step 2: Convert to UUID
```python
# Category model after UUID migration
class Category(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
