# CRICOS Finder

Небольшой Django-проект для поиска CRICOS-провайдеров, курсов и кампусов по Австралии.

## Установка и запуск

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 manage.py migrate
python3 manage.py createsuperuser
python3 manage.py runserver
```

## Импорт CRICOS

Проект хранит версии импорта в таблице `Dataset`. У текущего набора данных стоит `is_current=True`, у старых `False`.

Импорт с `data.gov.au`:

```bash
python3 manage.py import_cricos
```

Принудительно скачать заново:

```bash
python3 manage.py import_cricos --force-download --download-dir .
```

## Продакшен

Для продакшена есть файл `main/settings_production.py` и пример `supervisor.conf`.

Важно:

- в проекте сейчас есть захардкоженные секреты и хосты
- перед боевым запуском их нужно вынести в переменные окружения
- если будешь использовать `settings_production.py`, понадобится ещё `sentry-sdk`

Пример запуска через production settings:

```bash
DJANGO_SETTINGS_MODULE=main.settings_production python3 manage.py migrate
DJANGO_SETTINGS_MODULE=main.settings_production python3 manage.py runserver
```
