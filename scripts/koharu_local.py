"""Cliente del servidor MCP local de Koharu: inspeccion y procesamiento por sus herramientas oficiales."""
from __future__ import annotations
import argparse
import json
from urllib.request import Request, urlopen
from motores_abiertos import write


class KoharuClient:
    def __init__(self):
        self.url = 'http://127.0.0.1:7878/mcp'
        self.session = None
        self.counter = 0
        reply = self.request('initialize', {'protocolVersion': '2025-06-18',
            'capabilities': {}, 'clientInfo': {'name': 'manga-auto-project', 'version': '1.0'}})
        self.protocol = reply['protocolVersion']
        self.request('notifications/initialized', notification=True)

    def request(self, method, params=None, notification=False):
        self.counter += 1
        payload = {'jsonrpc': '2.0', 'method': method}
        if not notification:
            payload['id'] = self.counter
        if params is not None:
            payload['params'] = params
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
        if self.session:
            headers['Mcp-Session-Id'] = self.session
        if hasattr(self, 'protocol'):
            headers['MCP-Protocol-Version'] = self.protocol
        with urlopen(Request(self.url, json.dumps(payload).encode(), headers=headers), timeout=45) as response:
            self.session = response.headers.get('Mcp-Session-Id', self.session)
            body = response.read().decode()
        if not body.strip():
            return None
        if body.lstrip().startswith('{'):
            message = json.loads(body)
        else:
            messages = [json.loads(line[5:].strip()) for line in body.splitlines()
                        if line.startswith('data:') and line[5:].strip()]
            message = next(item for item in messages if item.get('id') == self.counter)
        if 'error' in message:
            raise ValueError(str(message['error']))
        return message.get('result')

    def tools(self):
        return self.request('tools/list')

    def call(self, name, arguments):
        if name not in {tool['name'] for tool in self.tools()['tools']}:
            raise ValueError('Herramienta no ofrecida por Koharu: ' + name)
        result = self.request('tools/call', {'name': name, 'arguments': arguments})
        if result.get('isError'):
            raise ValueError(str(result))
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--herramienta', help='Sin esta opcion, lista herramientas y esquemas')
    parser.add_argument('--argumentos', type=json.loads, default={})
    parser.add_argument('--salida', required=True)
    args = parser.parse_args()
    client = KoharuClient()
    result = client.call(args.herramienta, args.argumentos) if args.herramienta else client.tools()
    write(args.salida, result)
    print(args.salida)


if __name__ == '__main__':
    main()
