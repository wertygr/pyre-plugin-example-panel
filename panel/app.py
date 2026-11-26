import gc
import linecache
import queue
import sys
import threading

from plugins.plugin_tools.plugin_types import PluginApi, PluginData
from plugins.plugin_tools.meta import MagicFunction, fn_convert
import customtkinter as ctk

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")
ACCENT = "#a83232"
ACCENT_HOVER = "#7a2222"
OK = "#2b7a3d"
OK_HOVER = "#1f592c"
PLUGIN_PREFIX = "plugins."

def _tree_mod(name: str) -> dict:
    """folded view of sys.modules: root packages with children"""
    tree: dict[str, dict] = {}
    for name_mod in sorted(sys.modules):
        parts = name_mod.split(".")
        node = tree
        for i in range(1, len(parts) + 1):
            node = node.setdefault(".".join(parts[:i]), {})
    return tree

class App:
    def __init__(self, root: ctk.CTk, api: PluginApi, host: "_PersistentUIHost"):
        self.root = root
        self.api = api
        self.host = host
        self.data: PluginData = api["data"]
        self.expanded: set[str] = set()

        self.root.title("panel")
        self.root.geometry("780x520")
        self._build_ui()

    @property
    def alive(self) -> bool:
        return self.host.alive

    # ------------------------------------------------------------------ ui

    def _build_ui(self):
        self.tabview = ctk.CTkTabview(self.root)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=10)
        self.tab_modules = self.tabview.add("modules")
        self.tab_plugins = self.tabview.add("plugins")
        self.tab_cache = self.tabview.add("linecache")

        self._build_modules()
        self._build_plugins()
        self._build_cache()

    def _build_modules(self):
        tab = self.tab_modules

        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.pack(fill="x", pady=(0, 6))
        self.search_var = ctk.StringVar()
        ctk.CTkEntry(top, placeholder_text="search", textvariable=self.search_var, width=220).pack(side="left", padx=(0, 8))
        self.only_plugins = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(top, text="plugins only", variable=self.only_plugins, command=self.render_modules).pack(side="left")
        ctk.CTkLabel(top, text="", width=20).pack(side="left")
        ctk.CTkButton(top, text="update", width=80, command=self.render_modules).pack(side="left")

        self.scroll_modules = ctk.CTkScrollableFrame(tab, corner_radius=0)
        self.scroll_modules.pack(fill="both", expand=True)
        self.render_modules()

    def _build_plugins(self):
        tab = self.tab_plugins

        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.pack(fill="x", pady=(0, 6))
        ctk.CTkButton(top, text="update", width=80, command=self.render_plugins).pack(side="left", padx=(0, 8))
        ctk.CTkButton(top, text="async_start", width=110, fg_color=OK, hover_color=OK_HOVER, command=self._async_start).pack(side="left", padx=(0, 8))
        ctk.CTkButton(top, text="async_stop", width=110, fg_color=ACCENT, hover_color=ACCENT_HOVER, command=self._async_stop).pack(side="left")

        self.scroll_plugins = ctk.CTkScrollableFrame(tab, corner_radius=0)
        self.scroll_plugins.pack(fill="both", expand=True)
        self.render_plugins()

    def _build_cache(self):
        tab = self.tab_cache

        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.pack(fill="x", pady=(0, 6))
        ctk.CTkButton(top, text="update", width=80, command=self.render_cache).pack(side="left", padx=(0, 8))
        ctk.CTkButton(top, text="clean all", width=90, fg_color=ACCENT, hover_color=ACCENT_HOVER, command=self._cache_clean).pack(side="left")

        self.scroll_cache = ctk.CTkScrollableFrame(tab, corner_radius=0)
        self.scroll_cache.pack(fill="both", expand=True)
        self.render_cache()

    # ------------------------------------------------------------- modules

    def render_modules(self):
        for w in self.scroll_modules.winfo_children():
            w.destroy()

        search = self.search_var.get().strip().lower()
        tree = _tree_mod("x")
        row = 0

        def put(name: str, depth: int, count: int, has_children: bool):
            nonlocal row
            if search and search not in name:
                return
            if self.only_plugins.get() and not name.startswith(PLUGIN_PREFIX):
                if not any(child.startswith(PLUGIN_PREFIX) for child in self._children(tree, name)):
                    return
            lbl = ctk.CTkLabel(
                self.scroll_modules,
                text=("▸ " + name if has_children and name not in self.expanded else
                      "▾ " + name if has_children else "    " + name),
                anchor="w",
                text_color="#6fa8dc" if name.startswith(PLUGIN_PREFIX) else None,
            )
            lbl.grid(row=row, column=0, sticky="ew", padx=(10 + depth * 18, 8), pady=1)
            if has_children:
                lbl.bind("<Button-1>", lambda _, n=name: self._toggle(n))
            info = ctk.CTkLabel(self.scroll_modules, text=self._mod_info(name, count), anchor="w", text_color="gray")
            info.grid(row=row, column=1, sticky="ew", padx=8, pady=1)
            btn = ctk.CTkButton(self.scroll_modules, text="del", width=60, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                command=lambda n=name: self.del_module(n))
            btn.grid(row=row, column=2, padx=(4, 8), pady=1)
            row += 1

        self._walk(tree, 0, put)
        self.scroll_modules.grid_columnconfigure(0, weight=3)
        self.scroll_modules.grid_columnconfigure(1, weight=2)
        self.scroll_modules.grid_columnconfigure(2, weight=0)

    def _children(self, tree: dict, name: str) -> list[str]:
        node = tree
        for part in name.split("."):
            node = node.get(part, {})
        return list(node)

    def _walk(self, node: dict, depth: int, put):
        for name, children in node.items():
            folded = name not in self.expanded
            total = self._count(children)
            put(name, depth, total, bool(children))
            if not folded and children:
                self._walk(children, depth + 1, put)

    def _count(self, node: dict) -> int:
        n = 0
        for name, children in node.items():
            n += (1 if name in sys.modules else 0) + self._count(children)
        return n

    def _mod_info(self, name: str, count: int) -> str:
        mod = sys.modules.get(name)
        if mod is None:
            return "(unloaded)"
        file = getattr(mod, "__file__", None) or "builtin"
        if count:
            return f"{count} sub | {file}"
        return file

    def _toggle(self, name: str):
        if name in self.expanded:
            self.expanded.discard(name)
        else:
            self.expanded.add(name)
        self.render_modules()

    def del_module(self, name: str):
        if not self.validate(f"del module: {name}"):
            return
        dead = [m for m in sys.modules if m == name or m.startswith(name + ".")]
        for m in dead:
            sys.modules.pop(m, None)
        self.data.repl_mode.pop(name, None)
        self.data.plugin_list.discard(name)
        self.render_modules()

    # ------------------------------------------------------------- plugins

    def render_plugins(self):
        for w in self.scroll_plugins.winfo_children():
            w.destroy()

        status = self._async_status()
        header = f"async thread: {status['thread']}   running: {len(status['plugin'])}"
        ctk.CTkLabel(self.scroll_plugins, text=header, anchor="w", text_color="#6fa8dc").grid(row=0, column=0, columnspan=3, sticky="ew", padx=8, pady=(2, 8))

        row = 1
        for name in sorted(self.data.plugin_list):
            module = sys.modules.get(name)
            funcs = self._plugin_funcs(module)
            space = self.data.plugin_space.get(name)

            ctk.CTkLabel(self.scroll_plugins, text=name, anchor="w",
                         text_color="#6fa8dc").grid(row=row, column=0, sticky="ew", padx=8, pady=2)
            ctk.CTkLabel(self.scroll_plugins, text=funcs, anchor="w", text_color="gray").grid(row=row, column=1, sticky="ew", padx=8, pady=2)
            frame = ctk.CTkFrame(self.scroll_plugins, fg_color="transparent")
            frame.grid(row=row, column=2, sticky="e", padx=8)
            if name in self.data.async_state.plugin:
                ctk.CTkButton(frame, text="async_del", width=80, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                              command=lambda n=name: self._async_del(n)).pack(side="left", padx=2)
            else:
                ctk.CTkButton(frame, text="async_run", width=80, fg_color=OK, hover_color=OK_HOVER,
                              command=lambda n=name: self._async_run(n)).pack(side="left", padx=2)
            ctk.CTkButton(frame, text="unload", width=70, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                          command=lambda n=name: self._unload(n)).pack(side="left", padx=2)
            if space is not None:
                ctk.CTkButton(frame, text="space", width=70, command=lambda n=name: self._show_space(n)).pack(side="left", padx=2)
            row += 1

        self.scroll_plugins.grid_columnconfigure(0, weight=1)
        self.scroll_plugins.grid_columnconfigure(1, weight=2)
        self.scroll_plugins.grid_columnconfigure(2, weight=0)

    def _plugin_funcs(self, module) -> str:
        if module is None:
            return "not loaded"
        found = []
        for fn in MagicFunction:
            if hasattr(module, fn.fn_name) and fn.fn_type.is_i(getattr(module, fn.fn_name)):
                found.append(fn.fn_name)
        return ", ".join(found) or "no entry points"

    def _async_status(self) -> dict:
        thread = self.data.async_state.thread
        running = bool(thread is not None and thread.is_alive() and self.data.async_state.loop is not None)
        return {"thread": "running" if running else "stopped", "plugin": list(self.data.async_state.plugin)}

    def _show_space(self, name: str):
        space = self.data.plugin_space.get(name)
        if space is None:
            return
        self.text_window(f"plugin_space[{name}]", repr(space))

    def _run_command(self, command: str):
        """Hop into the async loop thread: command output is written to the REPL."""
        loop = self.data.async_state.loop
        if loop is None or not loop.is_running():
            return

        def call():
            self.api["pars_command"](self._fake_data(command))

        loop.call_soon_threadsafe(call)

    def _load(self, name: str):
        self._run_command(f"_._ load_plug {name}")

    def _unload(self, name: str):
        self._run_command(f"_._ unload_plug {name}")

    def _async_run(self, name: str):
        self._run_command(f"_._ async run {name}")

    def _async_del(self, name: str):
        self._run_command(f"_._ async del {name}")
        self.render_plugins()

    def _async_start(self):
        self._run_command("_._ async start")
        self.render_plugins()

    def _async_stop(self):
        self._run_command("_._ async stop")
        self.render_plugins()

    def _fake_data(self, command: str) -> PluginData:
        import copy
        fake: PluginData = copy.copy(self.data)
        fake.command = command
        fake.argv = command.split()
        fake.argc = len(fake.argv)
        fake.postfix = " ".join(fake.argv[2:])
        return fake

    # ------------------------------------------------------------ linecache

    def render_cache(self):
        for w in self.scroll_cache.winfo_children():
            w.destroy()

        ctk.CTkLabel(self.scroll_cache, text=f"cached files: {len(linecache.cache)}", anchor="w",
                     text_color="#6fa8dc").grid(row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=(2, 8))
        for row, name in enumerate(sorted(linecache.cache), start=1):
            lines = len(linecache.getlines(name))
            size = sum(len(line) for line in linecache.getlines(name))
            ctk.CTkLabel(self.scroll_cache, text=name, anchor="w").grid(row=row, column=0, sticky="ew", padx=8, pady=1)
            frame = ctk.CTkFrame(self.scroll_cache, fg_color="transparent")
            frame.grid(row=row, column=1, sticky="e", padx=8)
            ctk.CTkLabel(frame, text=f"{lines} lines / {size} ch", text_color="gray").pack(side="left", padx=(0, 6))
            ctk.CTkButton(frame, text="view", width=60, command=lambda n=name: self._cache_view(n)).pack(side="left", padx=2)
            ctk.CTkButton(frame, text="del", width=50, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                          command=lambda n=name: self._cache_del(n)).pack(side="left", padx=2)

        self.scroll_cache.grid_columnconfigure(0, weight=3)
        self.scroll_cache.grid_columnconfigure(1, weight=0)

    def _cache_view(self, name: str):
        text = "".join(linecache.getlines(name))
        self.text_window(name, text)

    def _cache_del(self, name: str):
        if not self.validate(f"del cache: {name}"):
            return
        linecache.cache.pop(name, None)
        self.render_cache()

    def _cache_clean(self):
        if not self.validate(f"clean all linecache({len(linecache.cache)} files)"):
            return
        linecache.cache.clear()
        self.render_cache()

    # ------------------------------------------------------------- dialogs

    def text_window(self, title: str, text: str):
        win = ctk.CTkToplevel(self.root)
        win.title(title)
        win.geometry("900x600")
        win.transient(self.root)
        box = ctk.CTkTextbox(win, wrap="none")
        box.pack(fill="both", expand=True, padx=6, pady=6)
        box.insert("1.0", text)

    def validate(self, message: str) -> bool:
        result = False
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("confirm")
        dialog.geometry("380x160")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        def on_yes():
            nonlocal result
            result = True
            dialog.destroy()

        def on_no():
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", on_no)
        ctk.CTkLabel(dialog, text=message, wraplength=340, justify="center").pack(expand=True, padx=20, pady=(20, 10))
        frame = ctk.CTkFrame(dialog, fg_color="transparent")
        frame.pack(pady=(0, 20))
        ctk.CTkButton(frame, text="Ok", width=120, fg_color=OK, hover_color=OK_HOVER, command=on_yes).pack(side="left", padx=10)
        ctk.CTkButton(frame, text="cancel", width=120, fg_color="gray40", hover_color="gray30", command=on_no).pack(side="left", padx=10)

        def watch():
            if not self.alive:
                on_no()
            elif dialog.winfo_exists():
                dialog.after(100, watch)

        dialog.after(100, watch)
        self.root.wait_window(dialog)
        return result

class _PersistentUIHost:
    def __init__(self):
        self.cmd_q: queue.Queue = queue.Queue()
        self.ready = threading.Event()
        self.root: ctk.CTk | None = None
        self.current_app: App | None = None
        self.alive = False

        self.thread = threading.Thread(
            target=self._run_loop, name="pyre-tk-host", daemon=True
        )
        self.thread.start()
        self.ready.wait()

    def _run_loop(self):
        self.root = ctk.CTk()
        self.root.withdraw()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(30, self._poll_queue)
        self.ready.set()
        self.root.mainloop()

    def _on_close(self):
        self.alive = False
        self._clear_children()
        if self.root is not None:
            self.root.withdraw()

    def _clear_children(self):
        if self.root is None:
            return
        for child in list(self.root.winfo_children()):
            try:
                child.destroy()
            except Exception:
                pass
        if self.current_app is not None:
            self.current_app.__dict__.clear()
            self.current_app = None
        gc.collect()

    def _poll_queue(self):
        try:
            while True:
                cmd, payload = self.cmd_q.get_nowait()
                if cmd == "mount":
                    self._clear_children()
                    app_cls, api, mounted = payload
                    self.current_app = app_cls(self.root, api, self)
                    self.alive = True
                    self.root.deiconify()
                    self.root.lift()
                    if mounted is not None:
                        mounted.set()
                elif cmd == "reset":
                    done_event = payload
                    self._on_close()
                    if done_event is not None:
                        done_event.set()
        except queue.Empty:
            pass
        finally:
            if self.root is not None:
                self.root.after(30, self._poll_queue)

    def mount(self, app_cls, api: PluginApi) -> None:
        mounted = threading.Event()
        self.cmd_q.put(("mount", (app_cls, api, mounted)))
        if threading.current_thread() is not self.thread:
            mounted.wait(timeout=2.0)
    def shutdown(self):
        self.alive = False
        done = threading.Event()
        self.cmd_q.put(("reset", done))
        if threading.current_thread() is not self.thread:
            done.wait(timeout=2.0)