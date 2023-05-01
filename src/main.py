import os
import sys
import threading
from functools import partial
from os.path import expanduser, join

import kivy
import yt_dlp
from kivy.app import App
from kivy.factory import Factory
from kivy.properties import DictProperty, NumericProperty, StringProperty
from kivy.uix.actionbar import ActionBar
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import AsyncImage
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.recycleview import RecycleView
from kivy.uix.scrollview import ScrollView
from kivy.utils import platform

from about import AboutPopup
from downloaderThread import DownloaderThread
from logger import YdlLogger
from settings.general import *
from settings.verbosity import *
from settings.workarounds import *
from status import STATUS_DONE, STATUS_ERROR, STATUS_IN_PROGRESS

if platform == "android":
    from android.storage import primary_external_storage_path
    from android.permissions import check_permission, request_permissions, Permission

from kivy.config import Config
Config.set('input', 'mouse', 'mouse,multitouch_on_demand')

class RV(RecycleView):
    pass


class ActionBarMain(ActionBar):
    pass


class LogPopup(Popup):
    log = StringProperty()
    index = NumericProperty()

    def __init__(self, log, index, **kwargs):
        super(LogPopup, self).__init__(**kwargs)
        self.log = log
        self.index = index


class FormatSelectPopup(Popup):
    meta = {}
    selected_format_id = []

    def __init__(self, meta, **kwargs):
        super(FormatSelectPopup, self).__init__(**kwargs)
        self.selected_format_id.clear()
        formats_sorted = sorted(meta["formats"], key=lambda k: k["format"])
        for format in formats_sorted:
            grid = self.ids.layout
            grid.add_widget(Label(text=format["format"] + " " + format["ext"]))
            checkbox = CheckBox(active=False, size_hint_x=None, width=100)
            callback = partial(self.on_checkbox_active, format["format_id"])
            checkbox.bind(active=callback)
            grid.add_widget(checkbox)

    def on_checkbox_active(self, format_id, instance, value):
        if value:
            self.selected_format_id.append(format_id)
        else:
            self.selected_format_id.remove(format_id)


class DownloadStatusBar(BoxLayout):
    url = StringProperty("")
    status = NumericProperty(STATUS_IN_PROGRESS)
    log = StringProperty("")
    index = NumericProperty()
    status_icon = StringProperty("img/loader.png")
    title = StringProperty("")
    percent = NumericProperty(0)
    ETA = StringProperty("")
    speed = StringProperty("")
    file_size = StringProperty("")
    popup = None

    def on_release_show_log_button(self):
        self.popup = LogPopup(self.log, self.index)
        self.popup.open()

    def on_status(self, instance, value):
        if value == STATUS_IN_PROGRESS:
            self.status_icon = "img/loader.png"
        elif value == STATUS_DONE:
            self.status_icon = "img/correct.png"
        elif value == STATUS_ERROR:
            self.status_icon = "img/cancel.png"

    def on_log(self, instance, value):
        if self.popup is not None and instance.index == self.popup.index:
            self.popup.log = value


class DownloaderLayout(BoxLayout):
    popup = None  # info display popup

    def on_press_button_info(self):
        app = App.get_running_app()
        try:
            if not bool(app.meta):
                with yt_dlp.YoutubeDL(app.ydl_opts) as ydl:
                    app.meta = ydl.sanitize_info(ydl.extract_info(app.url, download=False))

            self.popup = InfoDisplayPopup(app.meta)
            self.popup.open()
        except Exception as inst:
            print("Exception: " + str(inst))

    def on_format_select_popup_dismiss(self, url, ydl_opts, meta, instance):
        if instance.selected_format_id:
            self.start_download(
                url,
                {**ydl_opts, **{"format": ",".join(instance.selected_format_id)}},
                meta,
            )

    def on_press_button_download(self):
        app = App.get_running_app()
        try:
            if not bool(app.meta):
                with yt_dlp.YoutubeDL(app.ydl_opts) as ydl:
                    app.meta = ydl.sanitize_info(ydl.extract_info(app.url, download=False))
        except Exception as e:
            print("Error while trying to extract info: " + str(e))
            return

        format_method = app.config.get("general", "method")
        if format_method == "Ask":
            self.popup = FormatSelectPopup(app.meta)
            callback = partial(
                self.on_format_select_popup_dismiss, app.url, app.ydl_opts, app.meta
            )
            self.popup.bind(on_dismiss=callback)
            self.popup.open()

        else:
            self.start_download(app.url, app.ydl_opts, app.meta)

    def start_download(self, url, ydl_opts, meta):
        index = len(self.ids.rv.data)

        # Add UI status bar for this download
        self.ids.rv.data.append(
            {
                "url": url,
                "index": index,
                "log": "",
                "title": meta["title"],
                "status": STATUS_IN_PROGRESS,
            }
        )

        # Create a logger
        ydl_opts["logger"] = YdlLogger(self.ids.rv, index)

        # Run in a thread so the UI do not freeze when download
        t = DownloaderThread(url, ydl_opts, self.ids.rv.data[-1])
        t.start()


class RootLayout(Label):
    pass


class StatusIcon(Label):
    status = NumericProperty(1)


class DownloaderApp(App):
    meta = {}
    ydl_opts = {}
    url = StringProperty()

    def get_output_dir(self):
        if platform == "android":
            return os.getenv("EXTERNAL_STORAGE")
        return expanduser("~")

    def build_config(self, config):
        config.setdefaults(
            "general",
            {
                "method": "Preset",
                "preset": "best",
                "ignoreerrors": False,
                "filetmpl": "%(title)s_%(format)s.%(ext)s",
                "savedir": self.get_output_dir(),
            })

        config.setdefaults(
            "verbosity",
            {
                "quiet": False,
                "nowarning": False,
                "verbose": False,
            })

        config.setdefaults(
            "workarounds",
            {
                "nocheckcertificate": False,
                "prefer_insecure": platform == "android",
            })

    def build_settings(self, settings):
        settings.add_json_panel("general", self.config, data=general)
        settings.add_json_panel("verbosity", self.config, data=verbosity)
        settings.add_json_panel("workarounds", self.config, data=workarounds)

    def on_config_change(self, config, section, key, value):
        if key == "savedir":
            self.ydl_opts["outtmpl"] = join(
                value, self.config.get("general", "filetmpl")
            )
        elif key == "filetmpl":
            self.ydl_opts["outtmpl"] = join(
                self.config.get("general", "savedir"), value
            )
        elif key == "preset" or (key == "method" and value == "Preset"):
            self.ydl_opts["format"] = self.config.get("general", "preset")
        elif key == "method" and value == "Ask":
            self.ydl_opts.pop("format", None)
        else:
            self.ydl_opts[key] = value

    def build(self):
        if platform == "android" and not check_permission(
                "android.permission.WRITE_EXTERNAL_STORAGE"
        ):
            request_permissions([Permission.WRITE_EXTERNAL_STORAGE])

        self.ydl_opts["ignoreerrors"] = self.config.get("general", "ignoreerrors")
        self.ydl_opts["nocheckcertificate"] = self.config.get(
            "general", "nocheckcertificate"
        )
        self.ydl_opts["prefer_insecure"] = self.config.get("general", "prefer_insecure")
        self.ydl_opts["outtmpl"] = join(
            self.config.get("general", "savedir"),
            self.config.get("general", "filetmpl"),
        )

        if self.config.get("general", "method") == "Preset":
            self.ydl_opts["format"] = self.config.get("general", "preset")

        self.ydl_opts["quiet"] = self.config.get("verbosity", "quiet")
        self.ydl_opts["nowarning"] = self.config.get("verbosity", "nowarning")
        self.ydl_opts["verbose"] = self.config.get("verbosity", "verbose")

        self.use_kivy_settings = False
        return RootLayout()


if __name__ == "__main__":
    DownloaderApp().run()
