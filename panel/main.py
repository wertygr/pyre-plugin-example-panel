import sys

from plugins.plugin_tools.lib.base import base_destructor

import asyncio
from .app import App, _PersistentUIHost

from plugins.plugin_tools.plugin_types import PluginApi, CommandContext, PluginData

PLUGIN_NAME = "_panel_"

def _get_host() -> _PersistentUIHost:
    host = getattr(sys, "_pyre_ctk_host", None)
    if host is None or not hasattr(host, "cmd_q"):
        host = _PersistentUIHost()
        sys._pyre_ctk_host = host
    return host

def _start_app(api: PluginApi, state: dict) -> _PersistentUIHost:
    host = _get_host()
    host.mount(App, api)
    state["app"] = host
    return host


def main(api: PluginApi, command_context: CommandContext, plugin_space: dict) -> None:
    data: PluginData = api["data"]
    state = plugin_space.setdefault(PLUGIN_NAME, {})
    app: App|None = state.get("app")
    if app is None or not app.alive:
        app = _start_app(api, state)
    api["pft"]("[panel]: window is open", data)

async def async_main(api: PluginApi, plugin_space: dict) -> None:
    state = plugin_space.setdefault(PLUGIN_NAME, {})
    app: App|None = state.get("app")
    if app is None or not app.alive:
        app = _start_app(api, state)
    # the coroutine only waits; every tkinter call stays in the panel thread
    if app is None:
        return
    try:
        while app.alive:
            await asyncio.sleep(0.05)
    finally:
        app.shutdown()
        thread = state.get("thread")
        if thread is not None and thread.is_alive():
            # wait for the Tk thread to finish destroying the window
            for _ in range(40):
                if not thread.is_alive():
                    break
                await asyncio.sleep(0.05)
        if state.get("app") is app:
            state["app"] = None
            state["thread"] = None

def destructor(plugin_space: dict) -> None:
    state = plugin_space.pop(PLUGIN_NAME, None)
    host = None
    if isinstance(state, dict):
        host = state.get("app") or state.get("host")

    if host is None:
        host = getattr(sys, "_pyre_ctk_host", None)

    if host is not None and hasattr(host, "shutdown"):
        host.shutdown()

    base_destructor(__package__)
