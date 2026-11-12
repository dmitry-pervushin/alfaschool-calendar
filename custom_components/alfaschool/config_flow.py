"""UI configuration, options, and credential recovery for Alfa School."""

from datetime import datetime

import probatio as vol
from aiohttp import ClientError, CookieJar
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .client import AlfaSchoolClient
from .const import CONF_INTERVAL_HOURS, DEFAULT_INTERVAL_HOURS, DOMAIN
from .exceptions import AuthenticationError, ScheduleError
from .parser import MOSCOW


def interval_schema(default=DEFAULT_INTERVAL_HOURS):
    """Support daily, eight-hour, four-hour and other whole-hour intervals."""
    return vol.Schema(
        {
            vol.Required(CONF_INTERVAL_HOURS, default=default): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=168)
            )
        }
    )


class AlfaSchoolConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure a separate calendar for each school account."""

    VERSION = 1

    async def _validate(self, username, password):
        session = async_create_clientsession(
            self.hass, auto_cleanup=False, cookie_jar=CookieJar()
        )
        try:
            client = AlfaSchoolClient(session, username, password)
            month = datetime.now(MOSCOW).date().replace(day=1)
            await client.async_fetch_months({month})
        except AuthenticationError:
            return "invalid_auth"
        except ClientError, TimeoutError:
            return "cannot_connect"
        except ScheduleError:
            return "invalid_schedule"
        finally:
            session.detach()
        return None

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        """Validate credentials before creating an entry."""
        errors = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            await self.async_set_unique_id(username.casefold())
            self._abort_if_unique_id_configured()
            if error := await self._validate(username, user_input[CONF_PASSWORD]):
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=f"Alfa School ({username})",
                    data={
                        CONF_USERNAME: username,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                    options={
                        CONF_INTERVAL_HOURS: user_input[CONF_INTERVAL_HOURS],
                        CONF_NAME: user_input.get(CONF_NAME, "").strip(),
                    },
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(vol.Secret(CONF_PASSWORD)): str,
                    vol.Optional(CONF_NAME, default=""): str,
                    **interval_schema().schema,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data) -> ConfigFlowResult:
        """Request a replacement password without changing the account."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None) -> ConfigFlowResult:
        errors = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            if error := await self._validate(
                entry.data[CONF_USERNAME], user_input[CONF_PASSWORD]
            ):
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(vol.Secret(CONF_PASSWORD)): str}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Edit polling without re-entering credentials."""
        return AlfaSchoolOptionsFlow()


class AlfaSchoolOptionsFlow(OptionsFlow):
    """Configure the student's name and polling interval."""

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={
                    **user_input,
                    CONF_NAME: user_input.get(
                        CONF_NAME, self.config_entry.options.get(CONF_NAME, "")
                    ).strip(),
                }
            )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_NAME, default=self.config_entry.options.get(CONF_NAME, "")
                    ): str,
                    **interval_schema(
                        self.config_entry.options.get(
                            CONF_INTERVAL_HOURS, DEFAULT_INTERVAL_HOURS
                        )
                    ).schema,
                }
            ),
        )
