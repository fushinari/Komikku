# Copyright (C) 2019-2020 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import json

from gi.repository import Gio
from gi.repository import GLib


class Settings(Gio.Settings):
    """
    Gio.Settings handler
    Implements the basic dconf-settings as properties
    """

    # Default Settings instance
    instance = None

    def __init__(self):
        Gio.Settings.__init__(self)

    @staticmethod
    def new():
        """Create a new Settings object"""
        g_settings = Gio.Settings.new('info.febvre.Komikku')
        g_settings.__class__ = Settings
        return g_settings

    @staticmethod
    def get_default():
        """Return the default instance of Settings"""
        if Settings.instance is None:
            Settings.instance = Settings.new()

        return Settings.instance

    @property
    def background_color(self):
        """Return the reader's background color"""
        value = self.background_color_value

        if value == 0:
            return 'white'
        if value == 1:
            return 'black'
        return 'white'

    @property
    def background_color_value(self):
        """Return the reader's background color value"""
        return self.get_enum('background-color')

    @background_color.setter
    def background_color(self, color):
        """
        Set the reader's background color

        :param color: reader's background color
        :type color: string
        """
        if color == 'white':
            self.set_enum('background-color', 0)
        elif color == 'black':
            self.set_enum('background-color', 1)

    @property
    def borders_crop(self):
        return self.get_boolean('borders-crop')

    @borders_crop.setter
    def borders_crop(self, state):
        self.set_boolean('borders-crop', state)

    @property
    def credentials_storage_plaintext_fallback(self):
        return self.get_boolean('credentials-storage-plaintext-fallback')

    @credentials_storage_plaintext_fallback.setter
    def credentials_storage_plaintext_fallback(self, state):
        self.set_boolean('credentials-storage-plaintext-fallback', state)

    @property
    def dark_theme(self):
        return self.get_boolean('dark-theme')

    @dark_theme.setter
    def dark_theme(self, state):
        self.set_boolean('dark-theme', state)

    @property
    def downloader_state(self):
        return self.get_boolean('downloader-state')

    @downloader_state.setter
    def downloader_state(self, state):
        self.set_boolean('downloader-state', state)

    @property
    def desktop_notifications(self):
        return self.get_boolean('desktop-notifications')

    @desktop_notifications.setter
    def desktop_notifications(self, state):
        self.set_boolean('desktop-notifications', state)

    @property
    def fullscreen(self):
        return self.get_boolean('fullscreen')

    @fullscreen.setter
    def fullscreen(self, state):
        self.set_boolean('fullscreen', state)

    @property
    def long_strip_detection(self):
        return self.get_boolean('long-strip-detection')

    @long_strip_detection.setter
    def long_strip_detection(self, state):
        self.set_boolean('long-strip-detection', state)

    @property
    def new_chapters_auto_download(self):
        return self.get_boolean('new-chapters-auto-download')

    @new_chapters_auto_download.setter
    def new_chapters_auto_download(self, state):
        self.set_boolean('new-chapters-auto-download', state)

    @property
    def night_light(self):
        return self.get_boolean('night-light')

    @night_light.setter
    def night_light(self, state):
        self.set_boolean('night-light', state)

    @property
    def nsfw_content(self):
        return self.get_boolean('nsfw-content')

    @nsfw_content.setter
    def nsfw_content(self, state):
        self.set_boolean('nsfw-content', state)

    @property
    def reading_mode(self):
        """Return the reader's reading mode"""
        value = self.reading_mode_value

        if value == 0:
            return 'right-to-left'
        if value == 1:
            return 'left-to-right'
        if value == 2:
            return 'vertical'
        if value == 3:
            return 'webtoon'
        return 'right-to-left'

    @property
    def reading_mode_value(self):
        """Return the reader's reading mode value"""
        mode = -1
        try:
            # Before 0.22.0 reading mode was called reading direction
            mode = self.get_enum('reading-direction')
        except Exception:
            pass

        if mode < 0:
            mode = self.get_enum('reading-mode')

        return mode

    @reading_mode.setter
    def reading_mode(self, mode):
        """
        Set the reader's reading mode

        :param mode: reader's reading mode
        :type mode: string
        """
        try:
            # Before 0.22.0 reading mode was called reading direction
            # Clear previous key with -1 value (unused)
            self.get_enum('reading-direction')
            self.set_enum('reading-direction', -1)
        except Exception:
            pass

        if mode == 'right-to-left':
            self.set_enum('reading-mode', 0)
        elif mode == 'left-to-right':
            self.set_enum('reading-mode', 1)
        elif mode == 'vertical':
            self.set_enum('reading-mode', 2)
        elif mode == 'webtoon':
            self.set_enum('reading-mode', 3)

    @property
    def scaling(self):
        """Return the pages' scaling in reader"""
        value = self.scaling_value

        if value == 0:
            return 'screen'
        if value == 1:
            return 'width'
        if value == 2:
            return 'height'
        if value == 3:
            return 'original'
        return 'screen'

    @property
    def scaling_value(self):
        """Return the pages' scaling value in reader"""
        return self.get_enum('scaling')

    @scaling.setter
    def scaling(self, value):
        """
        Set the pages' scaling in reader

        :param value: pages' scaling
        :type value: string
        """
        if value == 'screen':
            self.set_enum('scaling', 0)
        elif value == 'width':
            self.set_enum('scaling', 1)
        elif value == 'height':
            self.set_enum('scaling', 2)
        elif value == 'original':
            self.set_enum('scaling', 3)

    def toggle_server(self, uid, state):
        settings = self.servers_settings

        if uid not in settings:
            settings[uid] = dict(
                langs={},
            )

        settings[uid]['enabled'] = state

        self.servers_settings = settings

    def toggle_server_lang(self, uid, lang, state):
        settings = self.servers_settings

        if uid not in settings:
            settings[uid] = dict(
                langs={},
                enabled=True,
            )

        settings[uid]['langs'][lang] = state

        self.servers_settings = settings

    @property
    def servers_settings(self):
        return json.loads(self.get_string('servers-settings'))

    @servers_settings.setter
    def servers_settings(self, state):
        self.set_string('servers-settings', json.dumps(state))

    def add_servers_language(self, code):
        codes = self.servers_languages
        if code not in codes:
            codes.append(code)

        self.servers_languages = codes

    def remove_servers_language(self, code):
        codes = self.servers_languages
        if code in codes:
            codes.remove(code)

        self.servers_languages = codes

    @property
    def servers_languages(self):
        return list(self.get_value('servers-languages'))

    @servers_languages.setter
    def servers_languages(self, codes):
        codes = GLib.Variant('as', codes)
        self.set_value('servers-languages', codes)

    @property
    def update_at_startup(self):
        return self.get_boolean('update-at-startup')

    @update_at_startup.setter
    def update_at_startup(self, state):
        self.set_boolean('update-at-startup', state)

    @property
    def window_size(self):
        """Return the window's size"""
        return tuple(self.get_value('window-size'))

    @window_size.setter
    def window_size(self, size):
        """
        Set the window's size

        :param size: [w, h] window's size
        :type size: list
        """
        size = GLib.Variant('ai', list(size))
        self.set_value('window-size', size)
