# -*- coding: utf-8 -*-

# Copyright (C) 2019 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from gettext import gettext as _
import datetime
import threading

from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk
from gi.repository.GdkPixbuf import InterpType
from gi.repository.GdkPixbuf import Pixbuf

import mangascan.config_manager
from mangascan.model import create_db_connection
from mangascan.model import Chapter


class Controls():
    is_visible = False
    reader = None

    def __init__(self, reader):
        self.reader = reader

        #
        # Top box (visible in fullscreen mode only)
        #
        self.top_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.top_box.set_valign(Gtk.Align.START)

        # Headerbar
        self.headerbar = Gtk.HeaderBar()

        # Back button
        self.back_button = Gtk.Button.new_from_icon_name('go-previous-symbolic', Gtk.IconSize.BUTTON)
        self.back_button.connect('clicked', self.reader.window.on_left_button_clicked, None)
        self.headerbar.pack_start(self.back_button)

        # Menu button
        self.menu_button = Gtk.MenuButton.new()
        self.menu_button.get_children()[0].set_from_icon_name('view-more-symbolic', Gtk.IconSize.MENU)
        self.menu_button.set_menu_model(self.reader.builder.get_object('menu-reader'))
        self.headerbar.pack_end(self.menu_button)

        # Unfullscreen button
        self.unfullscreen_button = Gtk.Button.new_from_icon_name('view-restore-symbolic', Gtk.IconSize.BUTTON)
        self.unfullscreen_button.connect('clicked', self.reader.window.toggle_fullscreen)
        self.headerbar.pack_end(self.unfullscreen_button)

        self.top_box.pack_start(self.headerbar, True, True, 0)
        self.reader.overlay.add_overlay(self.top_box)

        #
        # Bottom box
        #
        self.bottom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.bottom_box.get_style_context().add_class('reader-controls-bottom-box')
        self.bottom_box.set_valign(Gtk.Align.END)
        self.bottom_box.set_margin_left(12)
        self.bottom_box.set_margin_right(12)

        # Number of pages
        self.nb_pages_label = Gtk.Label()
        self.nb_pages_label.set_halign(Gtk.Align.START)
        self.bottom_box.pack_start(self.nb_pages_label, False, True, 4)

        # Chapter's pages slider: current / nb
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 2, 1)
        self.scale.connect('value-changed', self.on_scale_value_changed)

        self.bottom_box.pack_start(self.scale, True, True, 0)
        self.reader.overlay.add_overlay(self.bottom_box)

    def goto_page(self, index):
        if self.scale.get_value() == index:
            self.scale.emit('value-changed')
        else:
            self.scale.set_value(index)

    def hide(self):
        self.is_visible = False
        self.top_box.hide()
        self.bottom_box.hide()

    def init(self):
        chapter = self.reader.chapter

        # Set title & subtitle
        self.headerbar.set_title(chapter.manga.name)
        subtitle = chapter.title
        if chapter.manga.name in subtitle:
            subtitle = subtitle.replace(chapter.manga.name, '').strip()
        self.headerbar.set_subtitle(subtitle)

        self.scale.set_range(1, len(chapter.pages))
        self.nb_pages_label.set_text(str(len(chapter.pages)))

    def on_fullscreen(self):
        if self.is_visible:
            self.top_box.show_all()

    def on_scale_value_changed(self, scale):
        self.reader.render_page(int(scale.get_value()) - 1)

    def on_unfullscreen(self):
        if self.is_visible:
            self.top_box.hide()

    def set_scale_direction(self, inverted):
        self.scale.set_inverted(inverted)
        self.scale.set_value_pos(Gtk.PositionType.RIGHT if inverted else Gtk.PositionType.LEFT)
        self.bottom_box.set_child_packing(self.nb_pages_label, False, True, 4, Gtk.PackType.START if inverted else Gtk.PackType.END)

    def show(self):
        self.is_visible = True

        if self.reader.window._is_fullscreen:
            self.top_box.show_all()

        self.bottom_box.show_all()


class Reader():
    button_press_timeout_id = None
    chapter = None
    chapters_consulted = []
    default_double_click_time = Gtk.Settings.get_default().get_property('gtk-double-click-time')
    pixbuf = None
    size = None
    zoom = dict(active=False)

    def __init__(self, window):
        self.window = window
        self.builder = window.builder
        self.builder.add_from_resource('/info/febvre/MangaScan/ui/menu_reader.xml')

        self.title_label = self.builder.get_object('reader_page_title_label')
        self.subtitle_label = self.builder.get_object('reader_page_subtitle_label')

        self.viewport = self.builder.get_object('reader_page_viewport')
        self.scrolledwindow = self.viewport.get_parent()
        self.overlay = self.scrolledwindow.get_parent()

        self.image = Gtk.Image()
        self.viewport.add(self.image)

        # Spinner
        self.spinner_box = self.builder.get_object('spinner_box')
        self.overlay.add_overlay(self.spinner_box)

        # Controls
        self.controls = Controls(self)

        self.scrolledwindow.connect('button-press-event', self.on_button_press)

    @property
    def background_color(self):
        return self.chapter.manga.background_color or mangascan.config_manager.get_background_color()

    @property
    def reading_direction(self):
        return self.chapter.manga.reading_direction or mangascan.config_manager.get_reading_direction()

    @property
    def scaling(self):
        return self.chapter.manga.scaling or mangascan.config_manager.get_scaling()

    def add_actions(self):
        # Reading direction
        self.reading_direction_action = Gio.SimpleAction.new_stateful(
            'reader.reading-direction', GLib.VariantType.new('s'), GLib.Variant('s', 'right-to-left'))
        self.reading_direction_action.connect('change-state', self.on_reading_direction_changed)

        # Scaling
        self.scaling_action = Gio.SimpleAction.new_stateful(
            'reader.scaling', GLib.VariantType.new('s'), GLib.Variant('s', 'screen'))
        self.scaling_action.connect('change-state', self.on_scaling_changed)

        # Background color
        self.background_color_action = Gio.SimpleAction.new_stateful(
            'reader.background-color', GLib.VariantType.new('s'), GLib.Variant('s', 'white'))
        self.background_color_action.connect('change-state', self.on_background_color_changed)

        self.window.application.add_action(self.reading_direction_action)
        self.window.application.add_action(self.scaling_action)
        self.window.application.add_action(self.background_color_action)

    def hide_spinner(self):
        self.spinner_box.hide()
        self.spinner_box.get_children()[0].stop()

    def init(self, chapter, index=None):
        def run():
            if self.chapter.update_full():
                GLib.idle_add(complete, index)
            else:
                GLib.idle_add(error)

        def complete(index):
            self.chapter.manga.update(dict(last_read=datetime.datetime.now()))

            if index is None:
                index = self.chapter.last_page_read_index or 0
            elif index == 'first':
                index = 0
            elif index == 'last':
                index = len(self.chapter.pages) - 1

            self.hide_spinner()
            self.controls.init()
            self.controls.goto_page(index + 1)

        def error():
            self.hide_spinner()
            self.window.show_notification(_('Oops, failed to retrieve chapter info. Please try again.'))
            return False

        if index is None:
            # We come from library
            # Reset list of chapters consulted
            self.chapters_consulted = []
            self.show()

        self.chapter = chapter
        self.chapters_consulted.append(chapter)

        # Set title & subtitle
        self.title_label.set_text(chapter.manga.name)
        subtitle = chapter.title
        if chapter.manga.name in subtitle:
            subtitle = subtitle.replace(chapter.manga.name, '').strip()
        self.subtitle_label.set_text(subtitle)

        self.show_spinner()

        # Init settings
        self.set_reading_direction()
        self.set_scaling()
        self.set_background_color()

        thread = threading.Thread(target=run)
        thread.daemon = True
        thread.start()

    def on_background_color_changed(self, action, variant):
        value = variant.get_string()
        if value == self.chapter.manga.background_color:
            return

        self.chapter.manga.update(dict(background_color=value))
        self.set_background_color()

    def on_button_press(self, widget, event):
        if event.button == 1:
            if self.button_press_timeout_id is None and event.type == Gdk.EventType.BUTTON_PRESS:
                # Schedule single click event to be able to detect double click
                self.button_press_timeout_id = GLib.timeout_add(self.default_double_click_time + 100, self.on_single_click, event.copy())

            elif event.type == Gdk.EventType._2BUTTON_PRESS:
                # Remove scheduled single click event
                if self.button_press_timeout_id:
                    GLib.source_remove(self.button_press_timeout_id)
                    self.button_press_timeout_id = None

                GLib.idle_add(self.on_double_click, event.copy())

    def on_double_click(self, event):
        # Zoom/unzoom

        def adjust_scroll(hadj, h_value, v_value):
            hadj.disconnect(adjust_scroll_handler_id)

            def adjust():
                vadj = self.scrolledwindow.get_vadjustment()
                hadj.set_value(h_value)
                vadj.set_value(v_value)

            GLib.idle_add(adjust)

        hadj = self.scrolledwindow.get_hadjustment()
        vadj = self.scrolledwindow.get_vadjustment()

        if self.zoom['active'] is False:
            # Record hadjustment and vadjustment values
            self.zoom['orig_hadj_value'] = hadj.get_value()
            self.zoom['orig_vadj_value'] = vadj.get_value()

            # Adjust image to 100% of original size (arbitrary experimental choice)
            factor = 1
            orig_width = self.image.get_pixbuf().get_width()
            orig_height = self.image.get_pixbuf().get_height()
            zoom_width = self.pixbuf.get_width() * factor
            zoom_height = self.pixbuf.get_height() * factor
            ratio = zoom_width / orig_width

            if orig_width <= self.size.width:
                rel_event_x = event.x - (self.size.width - orig_width) / 2
            else:
                rel_event_x = event.x + hadj.get_value()
            if orig_height <= self.size.height:
                rel_event_y = event.y - (self.size.height - orig_height) / 2
            else:
                rel_event_y = event.y + vadj.get_value()

            h_value = rel_event_x * ratio - event.x
            v_value = rel_event_y * ratio - event.y

            adjust_scroll_handler_id = hadj.connect('changed', adjust_scroll, h_value, v_value)

            pixbuf = self.pixbuf.scale_simple(zoom_width, zoom_height, InterpType.BILINEAR)

            self.image.set_from_pixbuf(pixbuf)

            self.zoom['active'] = True
        else:
            adjust_scroll_handler_id = hadj.connect('changed', adjust_scroll, self.zoom['orig_hadj_value'], self.zoom['orig_vadj_value'])

            self.set_image()

            self.zoom['active'] = False

    def on_reading_direction_changed(self, action, variant):
        value = variant.get_string()
        if value == self.chapter.manga.reading_direction:
            return

        self.chapter.manga.update(dict(reading_direction=value))
        self.set_reading_direction()

    def on_resize(self):
        if self.pixbuf is None:
            return

        self.size = self.window.get_size()
        self.set_image()

    def on_scaling_changed(self, action, variant):
        value = variant.get_string()
        if value == self.chapter.manga.scaling:
            return

        self.chapter.manga.update(dict(scaling=value))
        self.set_scaling()
        self.set_image()

    def on_single_click(self, event):
        self.button_press_timeout_id = None

        if event.x < self.size.width / 3:
            # 1st third of the page
            if self.zoom['active']:
                return

            index = self.page_index + 1 if self.reading_direction == 'right-to-left' else self.page_index - 1
        elif event.x > 2 * self.size.width / 3:
            # Last third of the page
            if self.zoom['active']:
                return

            index = self.page_index - 1 if self.reading_direction == 'right-to-left' else self.page_index + 1
        else:
            # Center part of the page
            if self.controls.is_visible:
                self.controls.hide()
            else:
                self.controls.show()

            return

        if index >= 0 and index < len(self.chapter.pages):
            self.controls.goto_page(index + 1)
        elif index == -1:
            # Get previous chapter
            db_conn = create_db_connection()
            row = db_conn.execute(
                'SELECT * FROM chapters WHERE manga_id = ? AND rank = ?', (self.chapter.manga_id, self.chapter.rank - 1)).fetchone()
            db_conn.close()

            if row:
                self.init(Chapter(row=row), 'last')
        elif index == len(self.chapter.pages):
            # Get next chapter
            db_conn = create_db_connection()
            row = db_conn.execute(
                'SELECT * FROM chapters WHERE manga_id = ? AND rank = ?', (self.chapter.manga_id, self.chapter.rank + 1)).fetchone()
            db_conn.close()

            if row:
                self.init(Chapter(row=row), 'first')

        return False

    def render_page(self, index):
        def run():
            page_path = self.chapter.get_page_path(index)
            if page_path is None:
                if self.window.application.connected:
                    page_path = self.chapter.get_page(index)
                    if page_path is None:
                        GLib.idle_add(error)
                        return
                else:
                    self.window.show_notification(_('No Internet connection'))

            GLib.idle_add(complete, page_path)

        def complete(page_path):
            if page_path:
                self.pixbuf = Pixbuf.new_from_file(page_path)
            else:
                self.pixbuf = Pixbuf.new_from_resource('/info/febvre/MangaScan/images/missing_file.png')

            self.chapter.update(dict(
                last_page_read_index=index,
                read=index == len(self.chapter.pages) - 1,
                recent=0,
            ))

            self.size = self.viewport.get_allocation()
            self.set_image()

            self.image.show()

            self.hide_spinner()

            return False

        def error():
            self.hide_spinner()
            self.window.show_notification(_('Oops, failed to retrieve page. Please try again.'))
            return False

        self.zoom['active'] = False
        self.page_index = index

        self.show_spinner()

        thread = threading.Thread(target=run)
        thread.daemon = True
        thread.start()

    def set_background_color(self):
        self.background_color_action.set_state(GLib.Variant('s', self.background_color))
        if self.background_color == 'white':
            self.viewport.override_background_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(1, 1, 1, 1))
        else:
            self.viewport.override_background_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0, 0, 0, 1))

    def set_image(self):
        width = self.pixbuf.get_width()
        height = self.pixbuf.get_height()

        if self.scaling == 'width' or (self.scaling == 'screen' and self.size.width <= self.size.height):
            # Adapt image to width
            pixbuf = self.pixbuf.scale_simple(
                self.size.width,
                height / (width / self.size.width),
                InterpType.BILINEAR
            )
        elif self.scaling == 'height' or (self.scaling == 'screen' and self.size.width > self.size.height):
            # Adjust image to height
            pixbuf = self.pixbuf.scale_simple(
                width / (height / self.size.height),
                self.size.height,
                InterpType.BILINEAR
            )

        self.image.set_from_pixbuf(pixbuf)

    def set_reading_direction(self):
        self.reading_direction_action.set_state(GLib.Variant('s', self.reading_direction))
        self.controls.set_scale_direction(self.reading_direction == 'right-to-left')

    def set_scaling(self):
        self.scaling_action.set_state(GLib.Variant('s', self.scaling))

    def show(self):
        self.builder.get_object('menubutton').set_menu_model(self.builder.get_object('menu-reader'))
        self.builder.get_object('menubutton_image').set_from_icon_name('view-more-symbolic', Gtk.IconSize.MENU)

        self.image.clear()
        self.pixbuf = None
        self.controls.hide()

        if mangascan.config_manager.get_fullscreen():
            self.window.set_fullscreen()

        self.window.show_page('reader')

    def show_spinner(self):
        self.spinner_box.get_children()[0].start()
        self.spinner_box.show()
