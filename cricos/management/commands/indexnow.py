import redis
import requests
import json
from django.conf import settings
from .worker_basic import BasicCommand


class Command(BasicCommand):
    help = 'Send submitted URLs to IndexNow API from Redis queue'

    def add_arguments(self, parser):
        parser.add_argument(
            '--domain',
            required=True,
            help='Domain name (e.g. www.example.org) without protocol'
        )
        parser.add_argument(
            '--key',
            required=True,
            help='IndexNow key (32 hex characters)'
        )

    def handle(self, *args, **kwargs):
        super().handle(*args, **kwargs)

        stats = {
            "total": 0,
            "sent": 0,
            "errors": 0,
        }

        rds = redis.Redis(**settings.REDIS)


        self.log("Worker started. Waiting for messages in the queue...")
        empty_queue_counter = 0
        while not self.codebase_changed():
            try:
                task = rds.brpop(settings.REDIS_INDEXNOW, 1)
                if not task:
                    empty_queue_counter += 1
                    if empty_queue_counter % 100 == 0:
                        self.log("Queue is empty, waiting for tasks...")
                    continue

                stats["total"] += 1
                _, task_data = task

                try:
                    data = json.loads(task_data)
                    self.log(f"Processing new task: {data}")

                    response = requests.post("https://api.indexnow.org/indexnow", json={
                        "host": kwargs["domain"],
                        "key": kwargs["key"],
                        "keyLocation": f"https://{kwargs["domain"]}/{kwargs["key"]}.txt",
                        "urlList": [f"https://{kwargs["domain"]}{data['url']}"],
                    }, timeout=20)

                    if not response.ok:
                        raise Exception(f"IndexNow response: {response.status_code} {response.text}")

                    stats["sent"] += 1
                    self.log(f"📬 Successfully sent: {f"https://{kwargs["domain"]}{data['url']}"}")
                except json.JSONDecodeError as e:
                    stats["errors"] += 1
                    self.log(f"Failed to decode task data: {e}")
                    continue

            except Exception as e:
                stats["errors"] += 1
                self.log(f"Unexpected error: {str(e)}")
