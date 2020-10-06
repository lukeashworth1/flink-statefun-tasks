from ._types import TaskError
from statefun_tasks import TaskRequest, TaskResult, TaskException, try_serialise_json_then_pickle, deserialise_result

from google.protobuf.any_pb2 import Any
from kafka.errors import NoBrokersAvailable
from kafka import KafkaProducer, KafkaConsumer, TopicPartition

import logging
from uuid import uuid4
from threading import Thread
from typing import List
import asyncio
from concurrent.futures import Future


_log = logging.getLogger('FlinkTasks')


class FlinkTasksClient(object):
    def __init__(self, kafka_broker_url, topic, reply_topic):
        self._kafka_broker_url = kafka_broker_url
        self._requests = {}

        self._topic = topic
        self._reply_topic = reply_topic
        self._group_id = f'{self._reply_topic}.{str(uuid4())}' # unique for instance

        self._producer = KafkaProducer(bootstrap_servers=[kafka_broker_url])

        self._consumer = KafkaConsumer(
            self._reply_topic,
            bootstrap_servers=[self._kafka_broker_url],
            auto_offset_reset='latest',
            group_id=self._group_id)

        self._consumer_thread = Thread(target=self._consume, args=())
        self._consumer_thread.daemon = True
        self._consumer_thread.start()

    def send(self, fun, *args, **kwargs):
        task_id = str(uuid4())
        task_data = (args, kwargs)
        task_request = TaskRequest(id=task_id, type=fun.type_name)

        try_serialise_json_then_pickle(task_request, task_data)

        return self._send(task_request)

    async def send_async(self, fun, *args, **kwargs):
        future, _ = self.send(fun, *args, **kwargs)
        return await asyncio.wrap_future(future)

    def _send(self, task_request: TaskRequest):
        if task_request.id is None or task_request.id == "":
            raise ValueError('Task request is missing an id')

        if task_request.type is None or task_request.type == "":
            raise ValueError('Task request is missing a type')

        future = Future()
        self._requests[task_request.id] = future

        task_request.reply_topic = self._reply_topic

        key = task_request.id.encode('utf-8')
        val = task_request.SerializeToString()

        self._producer.send(topic=self._topic, key=key, value=val)
        self._producer.flush()

        return future, task_request.id
    
    def _consume(self):
        while True:
            try:
                for message in self._consumer: 
                    any = Any()
                    any.ParseFromString(message.value)

                    if any.Is(TaskException.DESCRIPTOR):
                        self._raise_exception(any)
                    elif any.Is(TaskResult.DESCRIPTOR):
                        self._return_result(any)
                          
            except Exception as ex:
                _log.warning(f"Exception in consumer thread - {ex}", exc_info=ex)

    def _return_result(self, any: Any):
        task_result = TaskResult()
        any.Unpack(task_result)

        correlation_id = task_result.correlation_id

        future = self._requests.get(correlation_id, None) 

        if future is not None:
            del self._requests[correlation_id]

            try:
                future.set_result(deserialise_result(task_result))
            except Exception as ex:
                future.set_exception(ex)

    def _raise_exception(self, any: Any):
        task_exception = TaskException()
        any.Unpack(task_exception)

        correlation_id = task_exception.correlation_id

        future = self._requests.get(correlation_id, None) 

        if future is not None:
            del self._requests[correlation_id]

            try:
                future.set_exception(TaskError(task_exception))
            except Exception as ex:
                future.set_exception(ex)
