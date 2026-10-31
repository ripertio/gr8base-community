# Technical Stack

## Application
- **Python 3.13 and Django 5.2** power the server-rendered web app, forms, routing, admin, and database models.
- **Django Templates, Pico CSS, custom CSS, and JavaScript** provide the responsive UI without a separate frontend framework. JavaScript is used for the photo lightbox; pages still render on the server.
- **django-allauth** provides account login and registration. **Argon2** is configured as the preferred password hasher.
- **WhiteNoise** serves collected static assets (CSS and JavaScript) from Django alongside Gunicorn.

## Data and deployment
- **PostgreSQL 17** stores application data; Django accesses it through its ORM and the psycopg driver.
- **Docker Compose** runs the web and database containers. Bind-mounted data directories persist database files and uploaded media.
- **Caddy** routes HTTPS traffic to the web container.
- **Gunicorn** production application server handling webrequests.

## Image processing
**Pillow** processes uploaded photos in `process_image` to limit storage and standardize display:
- Rejects files larger than 15 MB, unsupported formats, and images above 60 million pixels.
- Reads JPEG, PNG, WebP, MPO, and HEIF/HEIC images; **pillow-heif** adds HEIF support.
- Applies EXIF rotation, converts images to RGB, and resizes them to a maximum 1,600-pixel edge.
- Re-encodes images as WebP at quality 80 before saving.