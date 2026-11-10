"""Plugin "Rotinas" do Airflow: tela para gerenciar as rotinas (só para Admin).

O Airflow carrega cada .py da pasta plugins/ como módulo solto; por isso este arquivo usa
imports absolutos (a pasta plugins/ está no PYTHONPATH) e o plugins/.airflowignore deixa só
este __init__.py ser varrido.
"""
from airflow.plugins_manager import AirflowPlugin

from rotinas_web.app import app


class RotinasPlugin(AirflowPlugin):
    name = "rotinas"
    fastapi_apps = [{"app": app, "url_prefix": "/rotinas-app", "name": "Rotinas"}]
    external_views = [{"name": "Rotinas", "href": "/rotinas-app/", "destination": "nav", "url_route": "rotinas"}]
