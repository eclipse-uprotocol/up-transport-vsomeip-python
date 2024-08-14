from enum import IntFlag
from typing import Union

from uprotocol.communication.ustatuserror import UStatusError
from uprotocol.uri.factory.uri_factory import UriFactory
from uprotocol.uri.serializer.uriserializer import UriSerializer
from uprotocol.uri.validator.urivalidator import UriValidator
from uprotocol.v1.ucode_pb2 import UCode
from uprotocol.v1.uri_pb2 import UUri


class MessageFlag(IntFlag):
    """
    Message Flags for different types of messages
    """

    PUBLISH = 1
    NOTIFICATION = 2
    REQUEST = 4
    RESPONSE = 8


class Utils:
    """
    Utils
    """

    @staticmethod
    def split_u32_to_u16(value):
        """
        Split a 32-bit unsigned integer into two 16-bit unsigned integers
        :param value: 32-bit unsigned integer
        :return: Tuple of two 16-bit unsigned integers
        """
        if not 0 <= value <= 0xFFFFFFFF:
            raise ValueError("Value must be an unsigned 32-bit integer (0 to 4294967295)")

        most_significant_bits = (value >> 16) & 0xFFFF
        least_significant_bits = value & 0xFFFF

        return most_significant_bits, least_significant_bits

    @staticmethod
    def split_u32_to_u8(value):
        """
        Split a 32-bit unsigned integer into four 8-bit unsigned integers
        :param value: 32-bit unsigned integer
        :return: Tuple of four 8-bit unsigned integers
        """
        if not 0 <= value <= 0xFFFFFFFF:
            raise ValueError("Value must be an unsigned 32-bit integer (0 to 4294967295)")

        byte1 = (value >> 24) & 0xFF
        byte2 = (value >> 16) & 0xFF
        byte3 = (value >> 8) & 0xFF
        byte4 = value & 0xFF

        return byte1, byte2, byte3, byte4

    @staticmethod
    def pack_to_u32(value_one: int, value_two: int):
        """
        Pack two integers into a 32-bit unsigned integer
        :return:
        """
        return ((value_one & 0xFFFF) << 16) | (value_two & 0xFFFF)

    @staticmethod
    def any_uuri() -> UUri:
        """
        Create a UUri that matches any URI
        :return: UUri that matches any URI
        """
        return UUri(
            authority_name="*",
            ue_id=0x0000_FFFF,  # any instance, any service
            ue_version_major=0xFF,  # any
            resource_id=0xFFFF,  # any
        )

    @staticmethod
    def get_listener_message_type(source_uuri: UUri, sink_uuri: UUri = None) -> Union[MessageFlag, UStatusError]:
        """
        The table for mapping resource ID to message type:

        |   src rid   | sink rid | Publish | Notification | Request | Response |
        |-------------|----------|---------|--------------|---------|----------|
        | [8000-FFFF) |   None   |    V    |              |         |          |
        | [8000-FFFF) |     0    |         |      V       |         |          |
        |      0      | (0-8000) |         |              |    V    |          |
        |   (0-8000)  |     0    |         |              |         |    V     |
        |     FFFF    |     0    |         |      V       |         |    V     |
        |     FFFF    | (0-8000) |         |              |    V    |          |
        |      0      |   FFFF   |         |              |    V    |          |
        |   (0-8000)  |   FFFF   |         |              |         |    V     |
        | [8000-FFFF) |   FFFF   |         |      V       |         |          |
        |     FFFF    |   FFFF   |         |      V       |    V    |    V     |

        Some organization:
        - Publish: {[8000-FFFF), None}
        - Notification: {[8000-FFFF), 0}, {[8000-FFFF), FFFF}, {FFFF, 0}, {FFFF, FFFF}
        - Request: {0, (0-8000)}, {0, FFFF}, {FFFF, (0-8000)}, {FFFF, FFFF}
        - Response: {(0-8000), 0}, {(0-8000), FFFF}, (FFFF, 0), {FFFF, FFFF}

        :param source_uuri: The source UUri.
        :param sink_uuri: Optional sink UUri for request-response types.
        :return: MessageFlag indicating the type of message.
        :raises Exception: If the combination of source UUri and sink UUri is invalid.
        """
        flag = MessageFlag(0)

        rpc_range = range(1, 0x7FFF)
        nonrpc_range = range(0x8000, 0xFFFE)
        wildcard_resource_id = UriFactory.WILDCARD_RESOURCE_ID

        src_resource = source_uuri.resource_id

        # Notification / Request / Response
        if sink_uuri:
            dst_resource = sink_uuri.resource_id

            if (
                (src_resource in nonrpc_range and dst_resource == 0)
                or (src_resource in nonrpc_range and dst_resource == wildcard_resource_id)
                or (src_resource == wildcard_resource_id and dst_resource == 0)
                or (src_resource == wildcard_resource_id and dst_resource == wildcard_resource_id)
            ):
                flag |= MessageFlag.NOTIFICATION

            if (
                (src_resource == 0 and dst_resource in rpc_range)
                or (src_resource == 0 and dst_resource == wildcard_resource_id)
                or (src_resource == wildcard_resource_id and dst_resource in rpc_range)
                or (src_resource == wildcard_resource_id and dst_resource == wildcard_resource_id)
            ):
                flag |= MessageFlag.REQUEST

            if (
                (src_resource in rpc_range and dst_resource == 0)
                or (src_resource in rpc_range and dst_resource == wildcard_resource_id)
                or (src_resource == wildcard_resource_id and dst_resource == 0)
                or (src_resource == wildcard_resource_id and dst_resource == wildcard_resource_id)
            ):
                flag |= MessageFlag.RESPONSE

            if dst_resource == wildcard_resource_id and (
                src_resource in nonrpc_range or src_resource == wildcard_resource_id
            ):
                flag |= MessageFlag.PUBLISH

        # Publish
        elif src_resource in nonrpc_range or src_resource == wildcard_resource_id:
            flag |= MessageFlag.PUBLISH

        # Error handling
        if flag == MessageFlag(0):
            raise UStatusError.from_code_message(
                code=UCode.INTERNAL,
                message="Wrong combination of source UUri and sink UUri",
            )
        else:
            return flag

    @staticmethod
    def get_uuri_string(uri: UUri) -> str:
        """
        Get the string representation of the UUri.

        :param uri: Source/Sink UUri
        :return: String representation of the UUri.
        """
        if uri is None:
            return ""
        return UriSerializer.serialize(uri)

    @staticmethod
    def matches(source: str, sink: str, attributes) -> bool:
        """
        Return True if the source and sink URIs match the attributes.

        :param source: The source URI.
        :param sink: The sink URI.
        :param attributes: The attributes to compare against

        :return: True if the source and sink URIs match the attributes.
        """
        if attributes is None:
            return False
        source = UriSerializer.deserialize(source)
        sink = UriSerializer.deserialize(sink)
        if source == UriFactory.ANY:
            return UriValidator.matches(sink, attributes.sink)
        if sink == UriFactory.ANY:
            return UriValidator.matches(source, attributes.source)
        return UriValidator.matches(source, attributes.source) and UriValidator.matches(sink, attributes.sink)
