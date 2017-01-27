from channels.generic.websockets import WebsocketConsumer
import json
from six import string_types


class JsonRpcException(Exception):
    """
    >>> exc = JsonRpcException(1, JsonRpcWebsocketConsumer.INVALID_REQUEST)
    >>> str(exc)
    '{"jsonrpc": "2.0", "id": 1, "error": {"message": "Invalid Request", "code": -32600}}'

    """

    def __init__(self, rpc_id, code, data=None):
        self.rpc_id = rpc_id
        self.code = code
        self.data = data

    @property
    def message(self):
        return JsonRpcWebsocketConsumer.errors[self.code]

    def as_dict(self):
        if self.data:
            return {'jsonrpc': '2.0',
                    'id': self.rpc_id,
                    'error': {'code': self.code,
                              'message': self.message,
                              'data': self.data}}
        else:
            return {'jsonrpc': '2.0',
                    'id': self.rpc_id,
                    'error': {'code': self.code,
                              'message': self.message}}

    def __str__(self):
        return json.dumps(self.as_dict())


class JsonRpcWebsocketConsumer(WebsocketConsumer):
    """
    Variant of WebsocketConsumer that automatically JSON-encodes and decodes
    messages as they come in and go out. Expects everything to be text; will
    error on binary data.

    http://groups.google.com/group/json-rpc/web/json-rpc-2-0
    errors:
    code 	message 	meaning
    -32700 	Parse error 	Invalid JSON was received by the server.
            An error occurred on the server while parsing the JSON text.
    -32600 	Invalid Request 	The JSON sent is not a valid Request object.
    -32601 	Method not found 	The method does not exist / is not available.
    -32602 	Invalid params 	Invalid method parameter(s).
    -32603 	Internal error 	Internal JSON-RPC error.
    -32099 to -32000
            Server error 	Reserved for implementation-defined server-errors. (@TODO)

    """
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    GENERIC_APPLICATION_ERROR = -32000

    errors = dict()
    errors[PARSE_ERROR] = "Parse Error"
    errors[INVALID_REQUEST] = "Invalid Request"
    errors[METHOD_NOT_FOUND] = "Method Not Found"
    errors[INVALID_PARAMS] = "Invalid Params"
    errors[INTERNAL_ERROR] = "Internal Error"
    errors[GENERIC_APPLICATION_ERROR] = "Application Error"

    available_rpc_methods = dict()

    @classmethod
    def rpc_method(cls, rpc_name=None):
        """
        Decorator to list RPC methodds available. An optionnal name can be added
        :param rpc_name:
        :return: decorated function
        """
        def wrap(f):
            name = rpc_name if rpc_name is not None else f.func_name
            if cls.__name__ not in cls.available_rpc_methods:
                cls.available_rpc_methods[cls.__name__] = dict()
            cls.available_rpc_methods[cls.__name__][name] = f
        return wrap

    @classmethod
    def get_rpc_methods(cls):
        """
        Returns the RPC methods available for this consumer
        :return: list
        """
        if cls.__name__ not in cls.available_rpc_methods:
            return []
        return list(cls.available_rpc_methods[cls.__name__].keys())

    @staticmethod
    def error(id, code, message, data=None):

        """
        Error-type answer generator
        :param id: int
        :param code: code of the error
        :param message: message for the error
        :param data: (optional) error data
        :return: object
        """
        error_obj = {'code': code, 'message': message}
        if data is not None:
            error_obj['data'] = data

        return {
                    'jsonrpc': '2.0',
                    'id': id,
                    'error': error_obj
                    }

    def raw_receive(self, message, **kwargs):
        """
        Called when receiving a message.
        :param message: (string) message received
        :param kwargs:
        :return:
        """

        if "text" in message:
            try:
                data = json.loads(message['text'])
                if isinstance(data, dict):

                    if data.get('method') is not None and data.get('params') is not None and not data.get('id'):
                        # notification, we don't support it just yet
                        return

                    try:
                        result = self.__process(data)
                    except JsonRpcException as e:
                        result = e.as_dict()
                    except Exception as e:
                        result = self.error(data.get('id'), self.GENERIC_APPLICATION_ERROR, str(e), json.dumps(e.args))

                elif isinstance(data, list):
                    if len([x for x in data if not isinstance(x, dict)]):
                        result = self.error(None, self.INVALID_REQUEST, self.errors[self.INVALID_REQUEST])
            except ValueError as e:
                # json could not decoded
                result = self.error(None, self.PARSE_ERROR, self.errors[self.PARSE_ERROR])
            except Exception as e:
                result = self.error(None, self.INVALID_REQUEST, self.errors[self.INVALID_REQUEST])

        else:
            result = self.error(None, self.INVALID_REQUEST, self.errors[self.INVALID_REQUEST])

        self.send(result)

    def send(self, content, close=False):
        """
        Encode the given content as JSON and send it to the client.
        """
        super(JsonRpcWebsocketConsumer, self).send(text=json.dumps(content), close=close)

    @classmethod
    def group_send(cls, name, content, close=False):
        WebsocketConsumer.group_send(name, json.dumps(content), close=close)

    @classmethod
    def __process(cls, data):
        """
        Process the recived data
        :param data: object
        :return: object
        """

        if data.get('jsonrpc') != "2.0":
            raise JsonRpcException(data.get('id'), cls.INVALID_REQUEST)

        if 'method' not in data:
            raise JsonRpcException(data.get('id'), cls.INVALID_REQUEST)

        methodname = data['method']
        if not isinstance(methodname, string_types):
            raise JsonRpcException(data.get('id'), cls.INVALID_REQUEST)

        if methodname.startswith('_'):
            raise JsonRpcException(data.get('id'), cls.METHOD_NOT_FOUND)

        try:
            method = cls.available_rpc_methods[cls.__name__][methodname]
        except KeyError:
            raise JsonRpcException(data.get('id'), cls.METHOD_NOT_FOUND)
        params = data.get('params', [])

        if not isinstance(params, (list, dict)):
            raise JsonRpcException(data.get('id'), cls.INVALID_PARAMS)

        args = []
        kwargs = {}
        if isinstance(params, list):
            args = params
        elif isinstance(params, dict):
            kwargs.update(params)

        result = method(*args, **kwargs)

        return {
            'jsonrpc': '2.0',
            'id': data.get('id'),
            'result': result,
        }