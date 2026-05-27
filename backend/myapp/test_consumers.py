import asyncio
from unittest import IsolatedAsyncioTestCase

from myapp.consumers import DeviceMonitorConsumer


class _AsyncResource:
    def __init__(self):
        self.closed = False

    async def unsubscribe(self, *_args):
        self.closed = True

    async def aclose(self):
        self.closed = True


class DeviceMonitorConsumerTests(IsolatedAsyncioTestCase):
    async def test_disconnect_suppresses_cancelled_reader_task(self):
        consumer = DeviceMonitorConsumer()
        consumer.channel_name_key = "device_monitor:1"
        consumer.pubsub = _AsyncResource()
        consumer.redis = _AsyncResource()

        async def wait_forever():
            await asyncio.Future()

        consumer.reader_task = asyncio.create_task(wait_forever())
        await asyncio.sleep(0)

        await consumer.disconnect(1000)

        self.assertTrue(consumer.reader_task.cancelled())
        self.assertTrue(consumer.pubsub.closed)
        self.assertTrue(consumer.redis.closed)
