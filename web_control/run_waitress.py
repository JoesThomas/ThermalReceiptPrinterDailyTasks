import os

from waitress import serve

from app import app


if __name__ == "__main__":
    host = os.environ.get(
        "RECEIPT_WEB_HOST",
        "127.0.0.1",
    )

    port = int(
        os.environ.get(
            "RECEIPT_WEB_PORT",
            "5050",
        )
    )

    serve(
        app,
        host=host,
        port=port,
        threads=4,
    )
