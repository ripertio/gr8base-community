# Contributing

1. Open or pick an issue (use the templates for bugs and features).
2. Branch from `main`: `feature/<short-name>` or `fix/<short-name>`.
3. Run the app and tests in Docker, never in a local venv:
   ```bash
   docker compose -f docker-compose.dev.yml exec web python manage.py test
   ```
4. If you change models, include the migration (`makemigrations`).
5. Open a pull request into `main` and reference the issue (`Closes #n`). Keep `main` deployable: production is deployed from it.
