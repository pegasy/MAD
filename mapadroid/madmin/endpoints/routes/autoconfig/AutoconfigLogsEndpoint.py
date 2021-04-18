from typing import List

import aiohttp_jinja2
from aiohttp import web
from aiohttp.abc import Request
from aiohttp_jinja2.helpers import url_for

from mapadroid.db.helper.AutoconfigRegistrationHelper import AutoconfigRegistrationHelper
from mapadroid.db.model import AutoconfigRegistration
from mapadroid.madmin.RootEndpoint import RootEndpoint


class AutoconfigLogsEndpoint(RootEndpoint):
    """
    "/autoconfig/logs/<int:session_id>"
    """

    def __init__(self, request: Request):
        super().__init__(request)

    # TODO: Auth
    @aiohttp_jinja2.template('autoconfig_logs.html')
    async def get(self):
        session_id: int = int(self.request.match_info['session_id'])

        sessions: List[AutoconfigRegistration] = await AutoconfigRegistrationHelper \
            .get_all_of_instance(self._session, instance_id=self._get_instance_id(), session_id=session_id)

        if not sessions:
            raise web.HTTPFound(url_for('autoconfig_pending'))
        return {"subtab": "autoconf_dev",
                "responsive": str(self._get_mad_args().madmin_noresponsive).lower(),
                "session_id": session_id
                }
