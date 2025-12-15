# Pragati Server v2

## Project Overview

This project is a Python-based backend server built with the Flask framework. It serves as the API for the "Pragati" platform. The server uses MongoDB as its primary database and interacts with AWS S3 for file storage. Authentication is handled using JSON Web Tokens (JWT).

The application is structured using Flask Blueprints to organize routes into different modules, such as authentication, user management, ideas, and reports. The codebase is well-organized, with a clear separation of concerns between routes, services, and database interactions.

## Building and Running

### Prerequisites

- Python 3.10+
- MongoDB
- An AWS S3 bucket

### Installation

1.  **Clone the repository:**

    ```bash
    git clone <repository-url>
    cd pragati_server_v2
    ```

2.  **Create a virtual environment and install dependencies:**

    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
    pip install -r requirements.txt
    ```

3.  **Set up environment variables:**

    Create a `.env` file in the root directory and add the following variables:

    ```
    FLASK_ENV=development
    MONGO_URI=<your-mongodb-uri>
    JWT_SECRET=<your-jwt-secret>
    AWS_ACCESS_KEY_ID=<your-aws-access-key-id>
    AWS_SECRET_ACCESS_KEY=<your-aws-secret-access-key>
    S3_BUCKET=<your-s3-bucket-name>
    ```

### Running the application

To start the development server, run the following command:

```bash
flask run
```

The server will be accessible at `http://127.0.0.1:5000`.

For production, it is recommended to use a WSGI server like Gunicorn:

```bash
gunicorn "run:app"
```

## Development Conventions

*   **Code Style:** The project follows the PEP 8 style guide for Python code.
*   **Authentication:** API endpoints that require authentication are decorated with the `@requires_auth` decorator. The JWT must be included in the `Authorization` header as a Bearer token.
*   **Modularity:** The application is organized into modules using Flask Blueprints. Each module has a specific responsibility (e.g., `app/routes/auth.py` for authentication).
*   **Configuration:** Application configuration is managed in the `app/config.py` file and loaded based on the `FLASK_ENV` environment variable.
*   **Dependencies:** Project dependencies are listed in the `requirements.txt` file.
*   **Database:** The application uses MongoDB as its database, with interactions handled by the `pymongo` library.
*   **File Storage:** File uploads are handled by the `boto3` library and stored in an AWS S3 bucket.

## Project Structure

```
pragati_server_v2/
├── .flaskenv
├── .gitignore
├── requirements.txt
├── run.py
├── .vscode/
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── extensions.py
│   ├── database/
│   │   ├── __init__.py
│   │   └── mongo.py
│   ├── middleware/
│   │   ├── __init__.py
│   │   └── auth.py
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── admin.py
│   │   ├── analytics.py
│   │   ├── auth.py
│   │   ├── coordinator.py
│   │   ├── credits.py
│   │   ├── ideas.py
│   │   ├── mentors.py
│   │   ├── notifications.py
│   │   ├── principal.py
│   │   ├── psychometric.py
│   │   ├── reports_pdf.py
│   │   ├── reports.py
│   │   ├── search.py
│   │   ├── teams.py
│   │   └── users.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── auth_service.py
│   │   ├── email_service.py
│   │   ├── notification_service.py
│   │   ├── psychometric_service.py
│   │   └── s3_service.py
│   ├── templates/
│   │   └── report_template.html
│   └── utils/
│       ├── __init__.py
│       ├── id_helpers.py
│       ├── token_utils.py
│       └── validators.py
├── tests/
└── venv/
```