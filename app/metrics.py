"""Counts live chat connections on this server and (on AWS) publishes the number to CloudWatch
every minute. The ECS auto-scaling rule uses it to add servers when chat gets busy - CPU alone
is a poor signal for mostly-idle websockets."""
import logging
import os
import threading
import time

_sids = set()


def connected(sid):
    _sids.add(sid)


def disconnected(sid):
    _sids.discard(sid)


def current():
    return len(_sids)


def start_publisher(app):
    if os.environ.get("CLOUDWATCH_METRICS") != "1":
        return
    import boto3

    cw = boto3.client("cloudwatch", region_name=app.config["AWS_REGION"])
    service = os.environ.get("ECS_SERVICE_NAME", "community")

    def loop():
        while True:
            try:
                cw.put_metric_data(
                    Namespace="Community",
                    MetricData=[{
                        "MetricName": "ConnectionsPerTask",
                        "Dimensions": [{"Name": "Service", "Value": service}],
                        "Value": current(),
                        "Unit": "Count",
                    }],
                )
            except Exception:
                logging.exception("could not publish connection metric")
            time.sleep(60)

    threading.Thread(target=loop, daemon=True, name="metrics").start()
