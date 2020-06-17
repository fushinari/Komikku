# Copyright (C) 2019-2020 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _
import gi
import logging
import sys
from threading import Timer
import time

gi.require_version('Gtk', '3.0')
gi.require_version('Handy', '1')
gi.require_version('Notify', '0.7')

from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk
from gi.repository import Handy
from gi.repository import Notify
from gi.repository.GdkPixbuf import Pixbuf

from komikku.add_dialog import AddDialog
from komikku.card import Card
from komikku.activity_indicator import ActivityIndicator
from komikku.downloader import Downloader
from komikku.library import Library
from komikku.models import backup_db
from komikku.models import Settings
from komikku.preferences_window import PreferencesWindow
from komikku.reader import Reader
from komikku.updater import Updater

CREDITS = dict(
    developers=('Valéry Febvre (valos)', ),
    contributors=('Gerben Droogers (Tijder)', 'GrownNed', 'Mufeed Ali (lastweakness)', 'Romain Vaudois', 'Arthur Williams (TAAPArthur)', ),
    translators=('Ege Çelikçi (Turkish)', 'GrownNed (Russian)', 'Heimen Stoffels (Dutch)', 'VaGNaroK (Brazilian Portuguese)', 'Valéry Febvre (French)', ),
)


class Application(Gtk.Application):
    development_mode = False
    application_id = 'info.febvre.Komikku'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, application_id=self.application_id, flags=Gio.ApplicationFlags.FLAGS_NONE, **kwargs)
        self.window = None

    def add_actions(self):
        self.window.add_actions()

    def add_accelerators(self):
        self.window.add_accelerators()

    def do_startup(self):
        Gtk.Application.do_startup(self)

        GLib.set_application_name(_('Komikku'))
        GLib.set_prgname(self.application_id)

        Notify.init(_('Komikku'))

    def do_activate(self):
        if not self.window:
            self.window = ApplicationWindow(application=self, title='Komikku', icon_name=self.application_id)

            self.add_accelerators()
            self.add_actions()

        self.window.present()

    def get_logger(self):
        logging.basicConfig(
            format='%(asctime)s | %(levelname)s | %(name)s | %(message)s', datefmt='%d-%m-%y %H:%M:%S',
            level=logging.DEBUG if self.development_mode else logging.INFO,
        )
        logger = logging.getLogger()

        return logger


@Gtk.Template.from_resource('/info/febvre/Komikku/ui/application_window.ui')
class ApplicationWindow(Handy.ApplicationWindow):
    __gtype_name__ = 'ApplicationWindow'

    mobile_width = False
    page = None

    is_maximized = False
    is_fullscreen = False
    _prev_size = None

    titlebar = Gtk.Template.Child('titlebar')
    titlebar_revealer = Gtk.Template.Child('titlebar_revealer')
    headerbar = Gtk.Template.Child('headerbar')
    title_stack = Gtk.Template.Child('title_stack')
    left_button = Gtk.Template.Child('left_button')
    left_button_image = Gtk.Template.Child('left_button_image')
    search_button = Gtk.Template.Child('search_button')
    fullscreen_button = Gtk.Template.Child('fullscreen_button')
    menu_button = Gtk.Template.Child('menu_button')
    menu_button_image = Gtk.Template.Child('menu_button_image')

    box = Gtk.Template.Child('box')
    overlay = Gtk.Template.Child('overlay')
    stack = Gtk.Template.Child('stack')

    library_title_stack = Gtk.Template.Child('library_title_stack')
    library_searchentry = Gtk.Template.Child('library_searchentry')
    library_subtitle_label = Gtk.Template.Child('library_subtitle_label')
    library_flowbox = Gtk.Template.Child('library_flowbox')

    card_title_label = Gtk.Template.Child('card_title_label')
    card_stack = Gtk.Template.Child('card_stack')
    card_chapters_listbox = Gtk.Template.Child('card_chapters_listbox')
    card_info_grid = Gtk.Template.Child('card_info_grid')
    card_cover_image = Gtk.Template.Child('card_cover_image')
    card_authors_value_label = Gtk.Template.Child('card_authors_value_label')
    card_genres_value_label = Gtk.Template.Child('card_genres_value_label')
    card_status_value_label = Gtk.Template.Child('card_status_value_label')
    card_scanlators_value_label = Gtk.Template.Child('card_scanlators_value_label')
    card_server_value_label = Gtk.Template.Child('card_server_value_label')
    card_last_update_value_label = Gtk.Template.Child('card_last_update_value_label')
    card_synopsis_value_label = Gtk.Template.Child('card_synopsis_value_label')
    card_more_label = Gtk.Template.Child('card_more_label')

    reader_overlay = Gtk.Template.Child('reader_overlay')
    reader_viewport = Gtk.Template.Child('reader_viewport')
    reader_title_label = Gtk.Template.Child('reader_title_label')
    reader_subtitle_label = Gtk.Template.Child('reader_subtitle_label')

    notification_label = Gtk.Template.Child('notification_label')
    notification_revealer = Gtk.Template.Child('notification_revealer')

    first_start_grid = Gtk.Template.Child('first_start_grid')
    app_logo = Gtk.Template.Child('app_logo')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.application = kwargs['application']

        self._night_light_handler_id = 0
        self._night_light_proxy = None

        self.builder = Gtk.Builder()
        self.builder.add_from_resource('/info/febvre/Komikku/ui/menu/main.xml')

        self.logging_manager = self.application.get_logger()
        self.downloader = Downloader(self)
        self.updater = Updater(self, Settings.get_default().update_at_startup)

        self.activity_indicator = ActivityIndicator()
        self.overlay.add_overlay(self.activity_indicator)
        self.overlay.set_overlay_pass_through(self.activity_indicator, True)
        self.activity_indicator.show_all()

        self.assemble_window()

    def add_accelerators(self):
        self.application.set_accels_for_action('app.add', ['<Control>plus'])
        self.application.set_accels_for_action('app.enter-search-mode', ['<Control>f'])
        self.application.set_accels_for_action('app.fullscreen', ['F11'])
        self.application.set_accels_for_action('app.select-all', ['<Control>a'])
        self.application.set_accels_for_action('app.preferences', ['<Control>p'])
        self.application.set_accels_for_action('app.shortcuts', ['<Control>question'])

    def add_actions(self):
        about_action = Gio.SimpleAction.new('about', None)
        about_action.connect('activate', self.on_about_menu_clicked)
        self.application.add_action(about_action)

        add_action = Gio.SimpleAction.new('add', None)
        add_action.connect('activate', self.on_left_button_clicked)
        self.application.add_action(add_action)

        enter_search_mode_action = Gio.SimpleAction.new('enter-search-mode', None)
        enter_search_mode_action.connect('activate', self.enter_search_mode)
        self.application.add_action(enter_search_mode_action)

        fullscreen_action = Gio.SimpleAction.new('fullscreen', None)
        fullscreen_action.connect('activate', self.toggle_fullscreen)
        self.application.add_action(fullscreen_action)

        self.select_all_action = Gio.SimpleAction.new('select-all', None)
        self.select_all_action.connect('activate', self.select_all)
        self.application.add_action(self.select_all_action)

        preferences_action = Gio.SimpleAction.new('preferences', None)
        preferences_action.connect('activate', self.on_preferences_menu_clicked)
        self.application.add_action(preferences_action)

        shortcuts_action = Gio.SimpleAction.new('shortcuts', None)
        shortcuts_action.connect('activate', self.on_shortcuts_menu_clicked)
        self.application.add_action(shortcuts_action)

        self.library.add_actions()
        self.card.add_actions()
        self.reader.add_actions()

    def assemble_window(self):
        # Default size
        window_size = Settings.get_default().window_size
        self.set_default_size(window_size[0], window_size[1])

        # Min size
        geom = Gdk.Geometry()
        geom.min_width = 360
        geom.min_height = 288
        self.set_geometry_hints(None, geom, Gdk.WindowHints.MIN_SIZE)

        # Titlebar
        self.left_button.connect('clicked', self.on_left_button_clicked, None)
        self.fullscreen_button.connect('clicked', self.toggle_fullscreen, None)

        # Fisrt start grid
        pix = Pixbuf.new_from_resource_at_scale('/info/febvre/Komikku/images/logo.png', 256, 256, True)
        self.app_logo.set_from_pixbuf(pix)

        # Init stack pages
        self.library = Library(self)
        self.card = Card(self)
        self.reader = Reader(self)

        # Window
        self.connect('check-resize', self.on_resize)
        self.connect('delete-event', self.on_application_quit)
        self.connect('key-press-event', self.on_key_press)
        self.connect('window-state-event', self.on_window_state_event)
        self.titlebar_revealer.connect('notify::child-revealed', self.on_titlebar_toggle)

        # Custom CSS
        screen = Gdk.Screen.get_default()

        css_provider = Gtk.CssProvider()
        css_provider_resource = Gio.File.new_for_uri('resource:///info/febvre/Komikku/css/style.css')
        css_provider.load_from_file(css_provider_resource)

        context = Gtk.StyleContext()
        context.add_provider_for_screen(screen, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        if Gio.Application.get_default().development_mode is True:
            self.get_style_context().add_class('devel')

        # Theme (light or dark)
        self.init_theme()

        self.library.show()

    def change_layout(self):
        pass

    def confirm(self, title, message, callback):
        def on_response(dialog, response_id):
            if response_id == Gtk.ResponseType.YES:
                callback()

            dialog.destroy()

        dialog = Gtk.Dialog.new()
        dialog.set_transient_for(self)
        dialog.set_modal(True)
        dialog.get_style_context().add_class('solid-csd')
        dialog.connect('response', on_response)
        dialog.set_title(title)
        dialog.add_buttons('Yes', Gtk.ResponseType.YES, 'Cancel', Gtk.ResponseType.CANCEL)
        dialog.set_default_response(Gtk.ResponseType.YES)

        label = Gtk.Label()
        label.set_text(message)
        label.set_line_wrap(True)
        label.set_vexpand(True)
        label.set_property('margin', 16)
        label.set_valign(Gtk.Align.CENTER)
        label.set_halign(Gtk.Align.CENTER)
        label.set_justify(Gtk.Justification.CENTER)
        dialog.get_content_area().add(label)

        dialog.show_all()

    def enter_search_mode(self, action, param):
        if self.page == 'library':
            self.library.enter_search_mode()

    def hide_notification(self):
        self.notification_revealer.set_reveal_child(False)

    def init_theme(self):
        if Settings.get_default().night_light and not self._night_light_proxy:
            # Watch night light changes
            self._night_light_proxy = Gio.DBusProxy.new_sync(
                Gio.bus_get_sync(Gio.BusType.SESSION, None),
                Gio.DBusProxyFlags.NONE,
                None,
                'org.gnome.SettingsDaemon.Color',
                '/org/gnome/SettingsDaemon/Color',
                'org.gnome.SettingsDaemon.Color',
                None
            )

            def property_changed(proxy, changed_properties, invalidated_properties):
                properties = changed_properties.unpack()
                if 'NightLightActive' in properties.keys():
                    Gtk.Settings.get_default().set_property('gtk-application-prefer-dark-theme', properties['NightLightActive'])

            self._night_light_handler_id = self._night_light_proxy.connect('g-properties-changed', property_changed)

            Gtk.Settings.get_default().set_property(
                'gtk-application-prefer-dark-theme',
                self._night_light_proxy.get_cached_property('NightLightActive')
            )
        else:
            if self._night_light_proxy and self._night_light_handler_id > 0:
                self._night_light_proxy.disconnect(self._night_light_handler_id)
                self._night_light_proxy = None
                self._night_light_handler_id = 0

            Gtk.Settings.get_default().set_property('gtk-application-prefer-dark-theme', Settings.get_default().dark_theme)

    def on_about_menu_clicked(self, action, param):
        builder = Gtk.Builder()
        builder.add_from_resource('/info/febvre/Komikku/about_dialog.ui')

        about_dialog = builder.get_object('about_dialog')
        about_dialog.set_authors([
            *CREDITS['developers'], '',

            _('Contributors: Code, Patches, Debugging:'), '',
            *CREDITS['contributors'], '',
        ])
        about_dialog.set_translator_credits('\n'.join(CREDITS['translators']))
        about_dialog.set_modal(True)
        about_dialog.set_transient_for(self)
        if about_dialog.run() in (Gtk.ResponseType.CANCEL, Gtk.ResponseType.DELETE_EVENT):
            about_dialog.hide()

    def on_application_quit(self, window, event):
        def before_quit():
            self.save_window_size()
            backup_db()

        if self.downloader.running or self.updater.running:
            def confirm_callback():
                self.downloader.stop()
                self.updater.stop()

                while self.downloader.running or self.updater.running:
                    time.sleep(0.1)
                    continue

                before_quit()
                self.application.quit()

            message = [
                _('Are you sure you want to quit?'),
            ]
            if self.downloader.running:
                message.append(_('Some chapters are currently being downloaded.'))
            if self.updater.running:
                message.append(_('Some mangas are currently being updated.'))

            self.confirm(
                _('Quit?'),
                '\n'.join(message),
                confirm_callback
            )

            return True

        before_quit()
        return False

    def on_key_press(self, widget, event):
        """
        Go back navigation with <Escape> key:
        - Library <- Manga <- Reader
        - Exit selection mode (Library and Manga chapters)
        """
        if event.keyval == Gdk.KEY_Escape:
            self.on_left_button_clicked()
            return Gdk.EVENT_STOP

        return Gdk.EVENT_PROPAGATE

    def on_left_button_clicked(self, action=None, param=None):
        if self.page == 'library':
            if action and not self.library.selection_mode:
                AddDialog(self).open(action, param)
            if self.library.selection_mode:
                self.library.leave_selection_mode()
            if self.library.search_mode and action is None:
                self.library.leave_search_mode()
        elif self.page == 'card':
            if self.card.selection_mode:
                self.card.leave_selection_mode()
            else:
                self.library.show(invalidate_sort=True)
        elif self.page == 'reader':
            self.set_unfullscreen()

            # Refresh to update all previously chapters consulted (last page read may have changed)
            # and update info like disk usage
            self.card.refresh(self.reader.chapters_consulted)
            self.card.show()

    def on_resize(self, window):
        size = self.get_size()
        if self._prev_size and self._prev_size.width == size.width and self._prev_size.height == size.height:
            return

        self._prev_size = size

        self.library.on_resize()
        if self.page == 'reader':
            self.reader.on_resize()

        if size.width < 700:
            if self.mobile_width is True:
                return

            self.mobile_width = True
            self.change_layout()
        else:
            if self.mobile_width is True:
                self.mobile_width = False
                self.change_layout()

    def on_preferences_menu_clicked(self, action, param):
        PreferencesWindow(self).open(action, param)

    def on_shortcuts_menu_clicked(self, action, param):
        builder = Gtk.Builder()
        builder.add_from_resource('/info/febvre/Komikku/ui/shortcuts_overview.ui')

        shortcuts_overview = builder.get_object('shortcuts_overview')
        shortcuts_overview.set_modal(True)
        shortcuts_overview.set_transient_for(self)
        shortcuts_overview.present()

    def on_titlebar_toggle(self, *args):
        if self.page == 'reader':
            self.reader.pager.resize_pages()

    def on_window_state_event(self, widget, event):
        self.is_maximized = (event.new_window_state & Gdk.WindowState.MAXIMIZED) != 0
        self.is_fullscreen = (event.new_window_state & Gdk.WindowState.FULLSCREEN) != 0

    def save_window_size(self):
        if not self.is_maximized and not self.is_fullscreen:
            size = self.get_size()
            Settings.get_default().window_size = [size.width, size.height]

    def select_all(self, action, param):
        if self.page == 'library':
            self.library.select_all()
        elif self.page == 'card':
            self.card.chapters_list.select_all()

    def set_fullscreen(self):
        if not self.is_fullscreen:
            self.reader.controls.on_fullscreen()
            self.fullscreen()

    def set_unfullscreen(self):
        if self.is_fullscreen:
            self.reader.controls.on_unfullscreen()
            self.unfullscreen()

    def show_notification(self, message, interval=5):
        self.notification_label.set_text(message)
        self.notification_revealer.set_reveal_child(True)

        revealer_timer = Timer(interval, GLib.idle_add, args=[self.hide_notification])
        revealer_timer.start()

    def show_page(self, name, transition=True):
        if not transition:
            # Save defined transition type
            transition_type = self.stack.get_transition_type()
            # Set transition type to NONE
            self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
            self.title_stack.set_transition_type(Gtk.StackTransitionType.NONE)

        self.stack.set_visible_child_name(name)
        self.title_stack.set_visible_child_name(name)

        if not transition:
            # Restore transition type
            self.stack.set_transition_type(transition_type)
            self.title_stack.set_transition_type(transition_type)

        self.page = name

    def toggle_fullscreen(self, *args):
        if self.is_fullscreen:
            self.set_unfullscreen()
        else:
            self.set_fullscreen()


if __name__ == '__main__':
    app = Application()
    app.run(sys.argv)
