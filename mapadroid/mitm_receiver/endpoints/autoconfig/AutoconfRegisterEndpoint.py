from mapadroid.mitm_receiver.endpoints.AbstractDeviceAuthEndpoint import AbstractDeviceAuthEndpoint
from mapadroid.mitm_receiver.endpoints.AbstractMitmReceiverRootEndpoint import AbstractMitmReceiverRootEndpoint
from aiohttp import web


class AutoconfRegisterEndpoint(AbstractMitmReceiverRootEndpoint):
    """
    "/autoconfig/register"
    """

    # TODO: Auth/preprocessing for autoconfig?
    async def post(self):
        """ Device attempts to register with MAD.  Returns a session id for tracking future calls """
        status = 0
        #  TODO - auto-accept list
        if False:
            status = 1
        register_data = {
            'status': status,
            'ip': get_actual_ip(request),
            'instance_id': self._get_instance_id()
        }
        autoconfig_registration: AutoconfigRegistration = AutoconfigRegistration()
        autoconfig_registration.status = status
        autoconfig_registration.ip = self._get_request_address()
        autoconfig_registration.instance_id = self._get_instance_id()
        self._session.add(autoconfig_registration)
        await self._session.flush([autoconfig_registration])

        log_data = {
            'session_id': autoconfig_registration.session_id,
            'instance_id': self._get_instance_id(),
            'level': 2,
            'msg': 'Registration request from {}'.format(self._get_request_address())
        }
        await self.autoconfig_log(**log_data)
        return web.Response(status=201, body=str(session_id))