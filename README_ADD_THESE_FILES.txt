LEGACY_MAIN REMOVAL PATCH v8

Copy these files/folders into the root of your v7 project:

    main.py
    app.py
    services/
        __init__.py
        live_pipeline.py
    receipt/
        printer.py

You already have receipt/__init__.py in the full project; the copy included
here is harmless.

What this changes:
- main.py no longer imports legacy_main.
- app.py is the application-facing live orchestration entry point.
- the former live pipeline has been moved under services/live_pipeline.py and
  renamed run_live_pipeline(), so it is no longer a legacy application
  entrypoint.
- --preview, --validate and --health remain available.

IMPORTANT:
This patch removes the legacy_main.py dependency cleanly without changing all
external API behaviour at once. services/live_pipeline.py still contains the
existing collector functions (weather, calendar, finance, delivery, etc.).
Those can now be split into smaller service modules incrementally without
main.py depending on a legacy monolith.

Run after copying:
    python main.py --validate
    python -m unittest discover -v
    python main.py --preview
    python main.py