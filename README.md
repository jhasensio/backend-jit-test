# Enterprise Mock Web Server

A lightweight, Dockerized Python Flask web server designed to simulate a multi-departmental enterprise portal. This environment is built to generate localized, predictable HTTP traffic for testing network appliances, Web Application Firewalls (WAF), Deep Packet Inspection (DPI) rules, and load-balancing configurations without relying on external internet connectivity.

## Features

* **Complete Isolation:** Serves all static assets locally, preventing unwanted external CDN requests during packet capture and network inspection.
* **Dynamic Routing:** Utilizes Jinja2 templating to serve different departmental views (HR, Finance, Engineering) from a single HTML file.
* **Visual Theming:** Dynamically injects CSS variables to change UI colors and content based on the requested HTTP path, making it easy to visually verify routing rules.
* **Lightweight:** Built on `python:3.11-slim` for rapid container deployment and teardown.

## Project Structure

```text
mock-server/
├── app.py                 # Core Flask backend and routing logic
├── Dockerfile             # Container build instructions
├── requirements.txt       # Python dependencies (Flask, Werkzeug)
├── .gitignore             # Standard ignore file for Python and macOS
├── static/
│   └── logo.png           # Local static asset for isolated testing
└── templates/
    └── index.html         # Jinja2 dynamic HTML template
