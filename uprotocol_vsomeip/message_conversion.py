from uprotocol.communication.upayload import UPayload
from uprotocol.transport.builder.umessagebuilder import UMessageBuilder
from uprotocol.v1.uattributes_pb2 import UPayloadFormat
from uprotocol.v1.umessage_pb2 import UMessage
from uprotocol.v1.uri_pb2 import UUri

from uprotocol_vsomeip.utils import Utils


class VsomeipToUMessage:
    """
    Convert a VSOMEIP message to a UProtocol message.
    """

    @staticmethod
    def convert_to_publish_message(service_id, instance, event_id, data) -> UMessage:
        """
        Convert a VSOMEIP message to a UProtocol Publish message.
        :param service_id: The service ID.
        :param instance: The instance.
        :param event_id: The event ID.
        :param data: bytearray data from someip

        :return: The UProtocol message.
        """
        payload = UPayload.pack_from_data_and_format(bytes(data), UPayloadFormat.UPAYLOAD_FORMAT_UNSPECIFIED)
        ue_id = Utils.pack_to_u32(instance, service_id)
        # fixing major version to 1 as callback doesn't have major version
        message = UMessageBuilder.publish(
            source=UUri(
                ue_id=ue_id, resource_id=event_id, ue_version_major=1
            )  # todo: Need to reconstruct resource_id as well
        ).build_from_upayload(payload)

        return message

    @staticmethod
    def convert_to_request_message(service_id, instance, method_id, data, source_uri) -> UMessage:
        """
        Convert a VSOMEIP message to a UProtocol Request message.
        :param service_id: The service ID.
        :param instance: The instance.
        :param method_id: The RPC method ID.
        :param data: bytearray data from someip
        :param source_uri: The source URI.

        :return: The UProtocol message.
        """
        payload = UPayload.pack_from_data_and_format(bytes(data), UPayloadFormat.UPAYLOAD_FORMAT_UNSPECIFIED)
        message = UMessageBuilder.request(
            source=source_uri,
            sink=UUri(
                ue_id=Utils.pack_to_u32(instance, service_id),
                ue_version_major=1,
                resource_id=method_id,
            ),
            ttl=10000,
        ).build_from_upayload(payload)
        return message

    @staticmethod
    def convert_to_response_message(request_attributes, data) -> UMessage:
        """
        Convert a VSOMEIP message to a UProtocol Response message.
        :param request_attributes: The request attributes.
        :param data: bytearray data from someip

        :return: The UProtocol message.
        """
        payload = UPayload.pack_from_data_and_format(bytes(data), UPayloadFormat.UPAYLOAD_FORMAT_UNSPECIFIED)
        message = UMessageBuilder.response_for_request(request_attributes).build_from_upayload(payload)

        return message
