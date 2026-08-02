from app.celery_app import app


def test_footprint_enrichment_routes_to_analytics_queue() -> None:
    assert app.conf.task_routes["app.tasks.enrich_footprints"] == {"queue": "analytics"}


def test_named_place_enrichment_routes_to_serial_analytics_queue() -> None:
    assert app.conf.task_routes["app.tasks.enrich_news_places"] == {"queue": "analytics"}
