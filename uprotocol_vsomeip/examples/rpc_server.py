"""
SPDX-FileCopyrightText: 2024 Contributors to the Eclipse Foundation

See the NOTICE file(s) distributed with this work for additional
information regarding copyright ownership.

This program and the accompanying materials are made available under the
terms of the Apache License Version 2.0 which is available at

    http://www.apache.org/licenses/LICENSE-2.0

SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import logging
from datetime import datetime
from typing import List

from uprotocol.communication.inmemoryrpcserver import InMemoryRpcServer
from uprotocol.communication.requesthandler import RequestHandler
from uprotocol.communication.upayload import UPayload
from uprotocol.v1.uattributes_pb2 import UPayloadFormat
from uprotocol.v1.umessage_pb2 import UMessage
from uprotocol.v1.uri_pb2 import UUri

from uprotocol_vsomeip.vsomeip_utransport import VsomeipHelper, VsomeipTransport

logger = logging.getLogger()
LOG_FORMAT = "%(asctime)s [%(levelname)s] @ %(filename)s.%(module)s.%(funcName)s:%(lineno)d \n %(message)s"
logging.basicConfig(format=LOG_FORMAT, level=logging.getLevelName("DEBUG"))


class Helper(VsomeipHelper):
    """
    Helper class to provide list of services to be offered
    """

    def services_info(self) -> List[VsomeipHelper.UEntityInfo]:
        return [
            VsomeipHelper.UEntityInfo(
                service_id=1,
                events=[0, 10, 11],
                port=30511,
                major_version=1,
            )
        ]


class MyRequestHandler(RequestHandler):
    """
    Request Handler for the Service
    """

    def handle_request(self, msg: UMessage) -> UPayload:
        logger.debug("Request Received by Service Request Handler")
        attributes = msg.attributes
        payload = msg.payload
        source = attributes.source
        sink = attributes.sink
        logger.debug("Receive %s from %s to %s", payload, source, sink)
        response_payload = format(datetime.utcnow()).encode("utf-8")
        payload = UPayload(data=response_payload, format=UPayloadFormat.UPAYLOAD_FORMAT_TEXT)
        return payload


def create_method_uri():
    """
    Create a method URI
    """
    return UUri(authority_name="", ue_id=1, ue_version_major=1, resource_id=3)


async def register_rpc():
    """
    Main function to Register RPC to a service
    """
    transport = VsomeipTransport(helper=Helper(), source=UUri(ue_id=1, ue_version_major=1, resource_id=0))
    rpc_server = InMemoryRpcServer(transport)
    await rpc_server.register_request_handler(create_method_uri(), MyRequestHandler())

    while True:
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(register_rpc())
