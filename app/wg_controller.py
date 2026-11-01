"""Fixed sudo helper protocol; no shell or user-supplied command arguments."""
import json
import subprocess


class LocalWireGuardController:
    def _call(self, operation, **values):
        request = json.dumps({'operation': operation, **values}, separators=(',', ':'))
        result = subprocess.run(
            ['/usr/bin/sudo', '-n', '/usr/local/libexec/telegram-vpn-controller'],
            input=request, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=30, check=True,
        )
        response = json.loads(result.stdout)
        if not isinstance(response, dict) or response.get('ok') is not True or not isinstance(response.get('value'), dict):
            raise RuntimeError('unconfirmed controller response')
        return response['value']

    def list_peers(self):
        peers = self._call('list').get('peers')
        if not isinstance(peers, dict):
            raise ValueError('invalid response')
        return peers

    def server_details(self):
        return self._call('details')

    def add_if_free(self, public_key, address, expires_at):
        return self._call('add', key=public_key, address=address, expires_at=expires_at).get('confirmed') is True

    def remove_if_owned(self, public_key, address):
        return self._call('remove', key=public_key, address=address).get('confirmed') is True

    def is_owned(self, public_key, address):
        return self._call('owned', key=public_key, address=address).get('owned') is True
