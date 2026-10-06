from gevent import monkey

monkey.patch_all()  # must run before anything else imports sockets/ssl

from dotenv import load_dotenv  # noqa: E402

load_dotenv()  # reads .env for local development; in AWS real env vars are used

from app import create_app  # noqa: E402
from app.extensions import socketio  # noqa: E402

app = create_app()

from app import metrics  # noqa: E402

metrics.start_publisher(app)  # no-op unless CLOUDWATCH_METRICS=1 (set on AWS)

if __name__ == "__main__":  # local development: python wsgi.py
    socketio.run(app, host="0.0.0.0", port=8000, debug=False)
