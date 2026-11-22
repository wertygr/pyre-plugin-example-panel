from plugins.plugin_tools.meta import SUPPORTED_ASYNC_PLUGINS

if not SUPPORTED_ASYNC_PLUGINS:
    raise ValueError("the plugin loader does not support asynchrony")

import asyncio
from .app import App
import threading

from plugins.plugin_tools.plugin_types import PluginApi, CommandContext, PluginData

PLUGIN_NAME = "_panel_"

def _start_app(api: PluginApi, state: dict) -> "App":
    """Create and run the window entirely inside one dedicated thread: tkinter is not thread-safe."""
    holder: dict = {}
    ready = threading.Event()

    def target():
        try:
            app = App(api)
            holder["app"] = app
            ready.set()
            app.run()
        except Exception:
            if not ready.is_set():
                ready.set()

    thread = threading.Thread(target=target, name="pyre-panel", daemon=True)
    thread.start()
    ready.wait()
    app = holder.get("app")
    state["app"] = app
    state["thread"] = thread
    return app


def main(api: PluginApi, command_context: CommandContext, plugin_space: dict) -> None:
    data: PluginData = api["data"]
    if command_context["argv"][0] == "_._":
        return
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
    app: App|None = state.get("app") if isinstance(state, dict) else None
    if app is not None:
        app.shutdown()
