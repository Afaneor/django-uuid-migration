import uuid
from django.db import migrations, models
from django.apps import apps as django_apps

def generate_uuid_for_model(apps, schema_editor, model_name, app_name, pk_field):
    """
    Генерирует UUID для основной модели
    """
    db_alias = schema_editor.connection.alias
    Model = apps.get_model(app_name, model_name)
    for instance in Model.objects.using(db_alias).all():
        setattr(instance, f"{pk_field}_uuid", uuid.uuid4())
        instance.save()

def update_foreign_keys(apps, schema_editor, parent_model, child_model, app_name, child_app_name, fk_field, pk_field):
    """
    Обновляет Foreign Keys в дочерних моделях
    """
    db_alias = schema_editor.connection.alias
    ParentModel = apps.get_model(app_name, parent_model)
    ChildModel = apps.get_model(child_app_name, child_model)
    
    for child in ChildModel.objects.using(db_alias).all():
        try:
            parent_instance = ParentModel.objects.get(**{f"{pk_field}": getattr(child, f"{fk_field}_id")})
            setattr(child, f"{fk_field}_uuid", getattr(parent_instance, f"{pk_field}_uuid"))
            child.save()
        except ParentModel.DoesNotExist:
            # Обработка случая, когда родительский объект не существует
            # Например, если FK допускает null, можно установить None
            if ChildModel._meta.get_field(fk_field).null:
                setattr(child, f"{fk_field}_uuid", None)
                child.save()

def find_related_models(app_name, parent_model, apps_registry=None):
    """
    Автоматически находит все модели, которые имеют отношения к указанной модели
    
    Возвращает:
    - fk_models: список словарей с информацией о моделях с ForeignKey
    - implicit_m2m: список словарей с информацией о неявных M2M отношениях
    - through_models: список словарей с информацией о M2M через модели
    """
    if apps_registry is None:
        apps_registry = django_apps
        
    fk_models = []
    implicit_m2m = []
    through_models = []
    
    # Получаем модель, для которой ищем зависимости
    parent_model_obj = apps_registry.get_model(app_name, parent_model)
    
    # Проходим по всем моделям во всех приложениях
    for model in apps_registry.get_models():
        # Для каждой модели проверяем все поля
        for field in model._meta.fields:
            # Проверяем, является ли поле ForeignKey, ссылающимся на нашу модель
            if field.is_relation and field.related_model == parent_model_obj:
                fk_models.append({
                    'model': model._meta.object_name,
                    'app_name': model._meta.app_label,
                    'fk_field': field.name
                })
        
        # Проверяем M2M поля в других моделях
        for field in model._meta.many_to_many:
            if field.related_model == parent_model_obj:
                # Проверяем, использует ли поле промежуточную модель (through)
                if field.remote_field.through._meta.auto_created:
                    # Автоматически созданная (неявная) M2M модель
                    implicit_m2m.append({
                        'model': model._meta.object_name,
                        'app_name': model._meta.app_label,
                        'field_name': field.name
                    })
                else:
                    # Явно определенная through модель
                    through_model = field.remote_field.through
                    # Находим поле в through модели, которое ссылается на нашу родительскую модель
                    for through_field in through_model._meta.fields:
                        if through_field.is_relation and through_field.related_model == parent_model_obj:
                            through_models.append({
                                'model': through_model._meta.object_name,
                                'app_name': through_model._meta.app_label,
                                'field_name': through_field.name
                            })
    
    # Проверяем M2M поля в самой родительской модели
    for field in parent_model_obj._meta.many_to_many:
        if field.remote_field.through._meta.auto_created:
            # Автоматически созданная (неявная) M2M модель в нашей модели
            implicit_m2m.append({
                'model': parent_model,
                'app_name': app_name,
                'field_name': field.name,
                'related_model': field.related_model._meta.object_name,
                'related_app': field.related_model._meta.app_label
            })
        else:
            # Явно определенная through модель в нашей модели
            through_model = field.remote_field.through
            # Находим поле в through модели, которое ссылается на другую модель
            for through_field in through_model._meta.fields:
                if through_field.is_relation and through_field.related_model != parent_model_obj:
                    # Это поле ссылается на другую модель
                    related_model_field = through_field.name
                    # Находим поле, которое ссылается на нашу модель
                    for other_field in through_model._meta.fields:
                        if (other_field.is_relation and 
                            other_field.related_model == parent_model_obj and
                            other_field.name != through_field.name):
                            # Нашли поле, которое ссылается на нашу модель
                            parent_model_field = other_field.name
                            through_models.append({
                                'model': through_model._meta.object_name,
                                'app_name': through_model._meta.app_label,
                                'field_name': parent_model_field
                            })
    
    return fk_models, implicit_m2m, through_models

def generate_through_model_code(implicit_m2m):
    """
    Генерирует код для through моделей на основе неявных M2M отношений
    """
    through_models_code = {}
    migration_hints = {}
    
    for m2m in implicit_m2m:
        source_model = m2m['model']
        source_app = m2m['app_name']
        field_name = m2m['field_name']
        
        # Если это M2M в нашей модели
        if 'related_model' in m2m:
            target_model = m2m['related_model']
            target_app = m2m['related_app']
        else:
            # Если это M2M в другой модели, целью которого является наша модель
            target_model = m2m['model']
            target_app = m2m['app_name']
            source_model = m2m.get('related_model', source_model)
            source_app = m2m.get('related_app', source_app)
        
        # Генерируем имя для новой through модели
        through_model_name = f"{source_model}{target_model}Through"
        
        # Прогнозируем имя автоматически созданной M2M таблицы Django
        automatic_table_name = f"{source_app.lower()}_{source_model.lower()}_{field_name.lower()}"
        
        # Генерируем код модели с учетом предупреждений линтера
        model_code = f"""
class {through_model_name}(models.Model):
    {source_model.lower()} = models.ForeignKey('{source_app}.{source_model}', on_delete=models.CASCADE, db_index=True)
    {target_model.lower()} = models.ForeignKey('{target_app}.{target_model}', on_delete=models.CASCADE, db_index=True)
    # Дополнительные поля здесь
    
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['{source_model.lower()}', '{target_model.lower()}'], name='unique_{source_model.lower()}_{target_model.lower()}')
        ]
"""
        
        # Генерируем подсказку для миграционного файла
        migration_hint = f"""
# ВАЖНО: Простое изменение модели и создание обычной миграции НЕ СРАБОТАЕТ
# Вместо этого после создания through-модели {through_model_name}:
# 1. Создайте миграцию: python manage.py makemigrations
# 2. ОТРЕДАКТИРУЙТЕ файл миграции, заменив его содержимое на:

from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):

    dependencies = [
        ('{source_app}', 'XXXX_previous_migration'),  # Укажите предыдущую миграцию
    ]

    state_operations = [
        migrations.CreateModel(
            name='{through_model_name}',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('{source_model.lower()}', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='{source_app}.{source_model}', db_index=True)),
                ('{target_model.lower()}', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='{target_app}.{target_model}', db_index=True)),
                # Дополнительные поля модели здесь
            ],
        ),
        # Указываем Django использовать существующую таблицу для новой модели
        migrations.AlterModelTable(
            name='{through_model_name.lower()}',
            table='{automatic_table_name}',  # Имя автоматически созданной m2m таблицы
        ),
        # Меняем состояние модели для использования through
        migrations.AlterField(
            model_name='{source_model.lower()}',
            name='{field_name}',
            field=models.ManyToManyField(through='{source_app}.{through_model_name}', to='{target_app}.{target_model}'),
        ),
    ]

    operations = [
        # Обновляем только состояние Django, но не базу данных
        migrations.SeparateDatabaseAndState(state_operations=state_operations),
        # Добавляем необходимые дополнительные поля в существующую таблицу
        # migrations.AddField(
        #     model_name='{through_model_name}',
        #     name='some_extra_field',
        #     field=models.CharField(max_length=100, null=True),
        # ),
        # Возвращаем имя таблицы в нормальное состояние
        migrations.AlterModelTable(
            name='{through_model_name.lower()}',
            table=None,
        ),
    ]
"""
        
        through_models_code[through_model_name] = model_code
        migration_hints[through_model_name] = migration_hint
    
    return through_models_code, migration_hints

def create_uuid_migration(parent_model, app_name, dependencies, child_models=None, pk_field='id', auto_detect_relations=True):
    """
    Создает миграцию для преобразования целочисленного PK в UUID
    
    Параметры:
    - parent_model: имя основной модели, PK которой нужно изменить
    - app_name: имя приложения
    - dependencies: зависимости миграции
    - child_models: список словарей с именами дочерних моделей и FK-полями (опционально)
      формат: [{'model': 'ModelName', 'fk_field': 'field_name', 'app_name': 'app_name'}, ...]
    - pk_field: название поля primary key (по умолчанию 'id')
    - auto_detect_relations: автоматически определять связанные модели
    """
    operations = []
    
    # Автоматическое определение связанных моделей
    if auto_detect_relations:
        fk_related, implicit_m2m, through_models = find_related_models(app_name, parent_model)
        
        # Проверяем наличие неявных M2M и выдаем ошибку с рекомендациями
        if implicit_m2m:
            through_models_code, migration_hints = generate_through_model_code(implicit_m2m)
            error_message = (
                f"Обнаружены неявные M2M отношения для модели {parent_model}. "
                "Перед миграцией на UUID необходимо заменить их на явные through модели.\n\n"
                "Найдены следующие неявные M2M отношения:\n"
            )
            
            for i, m2m in enumerate(implicit_m2m):
                model = m2m['model']
                field = m2m['field_name']
                app = m2m['app_name']
                error_message += f"{i+1}. Модель {app}.{model}, поле {field}\n"
            
            error_message += "\n---------МОДЕЛИ THROUGH---------\n"
            error_message += "Создайте следующие through модели:\n\n"
            
            for through_name, code in through_models_code.items():
                error_message += f"# Модель {through_name}:\n{code}\n"
            
            error_message += "\n---------МИГРАЦИОННЫЕ ФАЙЛЫ---------\n"
            error_message += "ВАЖНО: Простое изменение модели не сработает! Необходимо использовать специальную технику миграции:\n\n"
            
            for through_name, hint in migration_hints.items():
                error_message += f"# Миграция для {through_name}:\n{hint}\n"
                
            error_message += (
                "\n---------ПОСЛЕ МИГРАЦИИ---------\n"
                "После создания through моделей и применения миграции, обновите ваши модели, заменив:\n"
                "tags = models.ManyToManyField(Tag)\n\n"
                "на:\n"
                "tags = models.ManyToManyField(Tag, through='ProductTagThrough')\n\n"
                "Только после этого запустите миграцию UUID."
            )
            
            raise ValueError(error_message)
        
        # Если child_models не указаны явно, используем найденные
        if child_models is None:
            child_models = fk_related
    
    # Если child_models все еще None, используем пустой список
    if child_models is None:
        child_models = []
    
    # 1. Добавляем UUID поле в родительскую модель
    operations.append(
        migrations.AddField(
            model_name=parent_model.lower(),
            name=f"{pk_field}_uuid",
            field=models.UUIDField(null=True),
        )
    )
    
    # 2. Генерируем UUID для каждой записи в родительской модели
    operations.append(
        migrations.RunPython(
            lambda apps, schema_editor: generate_uuid_for_model(
                apps, schema_editor, parent_model, app_name, pk_field
            )
        )
    )
    
    # 3. Обновляем UUID поле (делаем его обязательным и не редактируемым)
    operations.append(
        migrations.AlterField(
            model_name=parent_model.lower(),
            name=f"{pk_field}_uuid",
            field=models.UUIDField(default=uuid.uuid4, editable=False, serialize=False),
        )
    )
    
    # 4. Обрабатываем through модели если они есть и автоопределение включено
    if auto_detect_relations and through_models:
        for through in through_models:
            through_model = through['model']
            field_name = through['field_name']
            through_app = through.get('app_name', app_name)
            
            # 4.1. Добавляем UUID поле в through модель
            operations.append(
                migrations.AddField(
                    model_name=through_model.lower(),
                    name=f"{field_name}_uuid",
                    field=models.UUIDField(null=True),
                )
            )
            
            # 4.2. Обновляем UUID в through модели
            operations.append(
                migrations.RunPython(
                    lambda apps, schema_editor: update_foreign_keys(
                        apps, schema_editor, parent_model, through_model, 
                        app_name, through_app, field_name, pk_field
                    )
                )
            )
            
            # 4.3. Удаляем старое поле
            operations.append(
                migrations.RemoveField(
                    model_name=through_model.lower(),
                    name=field_name,
                )
            )
            
            # 4.4. Переименовываем UUID поле
            operations.append(
                migrations.RenameField(
                    model_name=through_model.lower(),
                    old_name=f"{field_name}_uuid",
                    new_name=field_name,
                )
            )
    
    # 5. Для каждой дочерней модели создаем соответствующие операции
    for child in child_models:
        child_model = child['model']
        fk_field = child['fk_field']
        child_app = child.get('app_name', app_name)
        
        # 5.1. Добавляем UUID поле в дочернюю модель
        operations.append(
            migrations.AddField(
                model_name=child_model.lower(),
                name=f"{fk_field}_uuid",
                field=models.UUIDField(null=True),
            )
        )
        
        # 5.2. Обновляем значения UUID в дочерней модели на основе родительской
        operations.append(
            migrations.RunPython(
                lambda apps, schema_editor: update_foreign_keys(
                    apps, schema_editor, parent_model, child_model, 
                    app_name, child_app, fk_field, pk_field
                )
            )
        )
        
        # 5.3. Удаляем старое FK поле
        operations.append(
            migrations.RemoveField(
                model_name=child_model.lower(),
                name=fk_field,
            )
        )
        
        # 5.4. Переименовываем UUID поле в оригинальное имя FK
        operations.append(
            migrations.RenameField(
                model_name=child_model.lower(),
                old_name=f"{fk_field}_uuid",
                new_name=fk_field,
            )
        )
    
    # 6. Удаляем старый PK из родительской модели
    operations.append(
        migrations.RemoveField(
            model_name=parent_model.lower(),
            name=pk_field,
        )
    )
    
    # 7. Переименовываем UUID поле в оригинальное имя PK
    operations.append(
        migrations.RenameField(
            model_name=parent_model.lower(),
            old_name=f"{pk_field}_uuid",
            new_name=pk_field,
        )
    )
    
    # 8. Устанавливаем новое поле как primary_key
    operations.append(
        migrations.AlterField(
            model_name=parent_model.lower(),
            name=pk_field,
            field=models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False),
        )
    )
    
    # 9. Для каждой дочерней модели устанавливаем ForeignKey
    for child in child_models:
        child_model = child['model']
        fk_field = child['fk_field']
        child_app = child.get('app_name', app_name)
        
        operations.append(
            migrations.AlterField(
                model_name=child_model.lower(),
                name=fk_field,
                field=models.ForeignKey(on_delete=models.CASCADE, to=f'{app_name}.{parent_model}')
            )
        )
    
    # 10. Для каждой through модели устанавливаем ForeignKey
    if auto_detect_relations and through_models:
        for through in through_models:
            through_model = through['model']
            field_name = through['field_name']
            through_app = through.get('app_name', app_name)
            
            operations.append(
                migrations.AlterField(
                    model_name=through_model.lower(),
                    name=field_name,
                    field=models.ForeignKey(on_delete=models.CASCADE, to=f'{app_name}.{parent_model}')
                )
            )
    
    # Создаем класс миграции
    migration_class = type('Migration', (migrations.Migration,), {
        'dependencies': dependencies,
        'operations': operations
    })
    
    return migration_class
