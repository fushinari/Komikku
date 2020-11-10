# Copyright (C) 2019-2020 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from copy import deepcopy
from gettext import gettext as _
from gettext import ngettext as n_
import math
import time

from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk
from gi.repository.GdkPixbuf import InterpType
from gi.repository.GdkPixbuf import Pixbuf
from gi.repository.GdkPixbuf import PixbufAnimation

from komikku.downloader import DownloadManagerDialog
from komikku.models import create_db_connection
from komikku.models import Manga
from komikku.models import update_rows
from komikku.importer import import_from_file
from komikku.servers import get_file_mime_type
from komikku.utils import scale_pixbuf_animation


class Library:
    search_menu_filters = {}
    search_mode = False
    selection_mode = False
    selection_mode_range = False
    selection_mode_last_thumbnail_index = None
    thumbnails_size = None

    def __init__(self, window):
        self.window = window
        self.builder = window.builder
        self.builder.add_from_resource('/info/febvre/Komikku/ui/menu/library_search.xml')
        self.builder.add_from_resource('/info/febvre/Komikku/ui/menu/library_selection_mode.xml')

        self.title_stack = self.window.library_title_stack
        self.subtitle_label = self.window.library_subtitle_label

        # Search
        self.search_menu_button = self.window.library_search_menu_button
        self.search_menu_button.set_menu_model(self.builder.get_object('menu-library-search'))
        self.search_entry = self.window.library_searchentry
        self.search_entry.connect('activate', self.on_search_entry_activate)
        self.search_entry.connect('changed', self.search)
        self.search_button = self.window.search_button
        self.search_button.connect('toggled', self.toggle_search_mode)

        # Mangas Flowbox
        self.flowbox = self.window.library_flowbox
        self.flowbox.connect('button-press-event', self.on_button_pressed)
        self.flowbox.connect('child-activated', self.on_manga_clicked)
        self.flowbox.connect('selected-children-changed', self.on_selection_changed)
        self.flowbox.connect('unselect-all', self.leave_selection_mode)
        self.gesture = Gtk.GestureLongPress.new(self.flowbox)
        self.gesture.set_touch_only(False)
        self.gesture.connect('pressed', self.on_gesture_long_press_activated)

        self.window.connect('key-press-event', self.on_key_press)
        self.window.updater.connect('manga-updated', self.on_manga_updated)

        def _filter(thumbnail):
            manga = thumbnail.manga
            term = self.search_entry.get_text().lower()
            ret = True

            # Search in name
            ret = term in manga.name.lower()

            # Search in server name
            ret = ret or term in manga.server.name.lower()

            # Search in genres (exact match)
            if manga.genres:
                ret = ret or term in [genre.lower() for genre in manga.genres]

            # Optional menu filters
            if ret and self.search_menu_filters.get('downloaded'):
                ret = manga.nb_downloaded_chapters > 0
            if ret and self.search_menu_filters.get('unread'):
                ret = manga.nb_unread_chapters > 0
            if ret and self.search_menu_filters.get('recents'):
                ret = manga.nb_recent_chapters > 0
            if ret and self.search_menu_filters.get('to-read'):
                ret = manga.nb_to_read_chapters > 0

            if not ret and thumbnail._selected:
                # Unselect thumbnail if it's selected
                self.flowbox.unselect_child(thumbnail)
                thumbnail._selected = False

            thumbnail._filtered = not ret

            return ret

        def _sort(thumbnail1, thumbnail2):
            """
            This function gets two children and has to return:
            - a negative integer if the firstone should come before the second one
            - zero if they are equal
            - a positive integer if the second one should come before the firstone
            """
            manga1 = thumbnail1.manga
            manga2 = thumbnail2.manga

            if manga1.last_read > manga2.last_read:
                return -1

            if manga1.last_read < manga2.last_read:
                return 1

            return 0

        self.populate()

        self.flowbox.set_filter_func(_filter)
        self.flowbox.set_sort_func(_sort)

    def add_actions(self):
        # Menu actions
        update_action = Gio.SimpleAction.new('library.update', None)
        update_action.connect('activate', self.update_all)
        self.window.application.add_action(update_action)

        download_manager_action = Gio.SimpleAction.new('library.download-manager', None)
        download_manager_action.connect('activate', self.open_download_manager)
        self.window.application.add_action(download_manager_action)

        importer_action = Gio.SimpleAction.new('library.importer', None)
        importer_action.connect('activate', self.show_file_chooser)
        self.window.application.add_action(importer_action)

        # Search menu actions
        search_downloaded_action = Gio.SimpleAction.new_stateful('library.search.downloaded', None, GLib.Variant('b', False))
        search_downloaded_action.connect('change-state', self.on_search_menu_action_changed)
        self.window.application.add_action(search_downloaded_action)

        search_unread_action = Gio.SimpleAction.new_stateful('library.search.unread', None, GLib.Variant('b', False))
        search_unread_action.connect('change-state', self.on_search_menu_action_changed)
        self.window.application.add_action(search_unread_action)

        search_recents_action = Gio.SimpleAction.new_stateful('library.search.recents', None, GLib.Variant('b', False))
        search_recents_action.connect('change-state', self.on_search_menu_action_changed)
        self.window.application.add_action(search_recents_action)

        search_to_read_action = Gio.SimpleAction.new_stateful('library.search.to-read', None, GLib.Variant('b', False))
        search_to_read_action.connect('change-state', self.on_search_menu_action_changed)
        self.window.application.add_action(search_to_read_action)

        # Menu actions in selection mode
        update_selected_action = Gio.SimpleAction.new('library.update-selected', None)
        update_selected_action.connect('activate', self.update_selected)
        self.window.application.add_action(update_selected_action)

        delete_selected_action = Gio.SimpleAction.new('library.delete-selected', None)
        delete_selected_action.connect('activate', self.delete_selected)
        self.window.application.add_action(delete_selected_action)

        download_selected_action = Gio.SimpleAction.new('library.download-selected', None)
        download_selected_action.connect('activate', self.download_selected)
        self.window.application.add_action(download_selected_action)

        mark_selected_read_action = Gio.SimpleAction.new('library.mark-selected-read', None)
        mark_selected_read_action.connect('activate', self.toggle_selected_read_status, 1)
        self.window.application.add_action(mark_selected_read_action)

        mark_selected_unread_action = Gio.SimpleAction.new('library.mark-selected-unread', None)
        mark_selected_unread_action.connect('activate', self.toggle_selected_read_status, 0)
        self.window.application.add_action(mark_selected_unread_action)

        select_all_action = Gio.SimpleAction.new('library.select-all', None)
        select_all_action.connect('activate', self.select_all)
        self.window.application.add_action(select_all_action)

    def add_manga(self, manga, position=-1):
        thumbnail = Thumbnail(self.window, manga, *self.thumbnails_size)
        self.flowbox.insert(thumbnail, position)

    def compute_thumbnails_size(self):
        default_width = 180
        default_height = 250

        container_width = self.window.get_size().width
        padding = 6  # flowbox children padding is set via CSS
        child_width = default_width + padding * 2
        if container_width / child_width != container_width // child_width:
            nb = container_width // child_width + 1
            width = container_width // nb - (padding * 2)
            height = default_height // (default_width / width)
        else:
            width = default_width
            height = default_height

        self.thumbnails_size = (width, height)

    def delete_selected(self, _action, _param):
        def confirm_callback():
            # Stop Downloader & Updater
            self.window.downloader.stop()
            self.window.updater.stop()

            while self.window.downloader.running or self.window.updater.running:
                time.sleep(0.1)
                continue

            # Safely delete mangas in DB
            for thumbnail in self.flowbox.get_selected_children():
                thumbnail.manga.delete()

            # Restart Downloader & Updater
            self.window.downloader.start()
            self.window.updater.start()

            # Finally, update library
            self.populate()

            self.leave_selection_mode()

        self.window.confirm(
            _('Delete?'),
            _('Are you sure you want to delete selected mangas?'),
            confirm_callback
        )

    def download_selected(self, _action, _param):
        chapters = []
        for thumbnail in self.flowbox.get_selected_children():
            for chapter in thumbnail.manga.chapters:
                chapters.append(chapter)

        self.leave_selection_mode()

        self.window.downloader.add(chapters)
        self.window.downloader.start()

    def enter_search_mode(self):
        self.search_button.set_active(True)

    def enter_selection_mode(self, x=None, y=None, selected_thumbnail=None):
        # Hide search button: disable search
        self.search_button.hide()

        self.selection_mode = True

        self.flowbox.set_selection_mode(Gtk.SelectionMode.MULTIPLE)

        if selected_thumbnail is None:
            if x is not None and y is not None:
                selected_thumbnail = self.flowbox.get_child_at_pos(x, y)
            else:
                selected_thumbnail = self.flowbox.get_child_at_index(0)

        self.flowbox.select_child(selected_thumbnail)
        selected_thumbnail._selected = True
        self.selection_mode_last_thumbnail_index = selected_thumbnail.get_index()

        self.window.headerbar.get_style_context().add_class('selection-mode')
        self.window.left_button_image.set_from_icon_name('go-previous-symbolic', Gtk.IconSize.MENU)
        self.window.menu_button.set_menu_model(self.builder.get_object('menu-library-selection-mode'))

    def leave_search_mode(self):
        self.search_button.set_active(False)

    def leave_selection_mode(self, _param=None):
        self.selection_mode = False

        # Show search button: re-enable search
        self.search_button.show()

        self.flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        for thumbnail in self.flowbox.get_children():
            thumbnail._selected = False

        self.window.headerbar.get_style_context().remove_class('selection-mode')
        self.window.left_button_image.set_from_icon_name('list-add-symbolic', Gtk.IconSize.MENU)
        self.window.menu_button.set_menu_model(self.builder.get_object('menu'))

    def on_button_pressed(self, _widget, event):
        thumbnail = self.flowbox.get_child_at_pos(event.x, event.y)
        if not self.selection_mode and event.type == Gdk.EventType.BUTTON_PRESS and event.button == 3 and thumbnail is not None:
            self.enter_selection_mode(selected_thumbnail=thumbnail)
            return Gdk.EVENT_STOP

        return Gdk.EVENT_PROPAGATE

    def on_gesture_long_press_activated(self, _gesture, x, y):
        if self.selection_mode:
            # Enter in 'Range' selection mode
            # Long press on a manga then long press on another to select everything in between
            self.selection_mode_range = True

            selected_thumbnail = self.flowbox.get_child_at_pos(x, y)
            self.flowbox.select_child(selected_thumbnail)
            self.on_manga_clicked(self.flowbox, selected_thumbnail)
        else:
            self.enter_selection_mode(x, y)

    def on_key_press(self, _widget, event):
        """Search can be triggered by simply typing a printable character"""

        if self.window.page != 'library':
            return Gdk.EVENT_PROPAGATE

        modifiers = event.get_state() & Gtk.accelerator_get_default_mod_mask()
        is_printable = GLib.unichar_isgraph(chr(Gdk.keyval_to_unicode(event.keyval)))
        if is_printable and modifiers in (Gdk.ModifierType.SHIFT_MASK, 0) and not self.search_mode:
            self.enter_search_mode()

        return Gdk.EVENT_PROPAGATE

    def on_manga_added(self, manga):
        """Called from 'Add dialog' when user clicks on [+] button"""
        db_conn = create_db_connection()
        nb_mangas = db_conn.execute('SELECT count(*) FROM mangas').fetchone()[0]
        db_conn.close()

        if nb_mangas == 1:
            # Library was previously empty
            self.populate()
        else:
            self.add_manga(manga, position=0)

    def on_manga_clicked(self, _flowbox, thumbnail):
        _ret, state = Gtk.get_current_event_state()
        modifiers = state & Gtk.accelerator_get_default_mod_mask()

        # Enter selection mode if <Control>+Click or <Shift>+Click is done
        if modifiers in (Gdk.ModifierType.CONTROL_MASK, Gdk.ModifierType.SHIFT_MASK) and not self.selection_mode:
            self.enter_selection_mode(selected_thumbnail=thumbnail)
            return Gdk.EVENT_PROPAGATE

        if self.selection_mode:
            if modifiers == Gdk.ModifierType.SHIFT_MASK:
                # Enter range selection mode if <Shift>+Click is done
                self.selection_mode_range = True
            if self.selection_mode_range and self.selection_mode_last_thumbnail_index is not None:
                # Range selection mode: select all mangas between last selected manga and clicked manga
                walk_index = self.selection_mode_last_thumbnail_index
                last_index = thumbnail.get_index()

                while walk_index != last_index:
                    walk_thumbnail = self.flowbox.get_child_at_index(walk_index)
                    if walk_thumbnail and not walk_thumbnail._selected:
                        self.flowbox.select_child(walk_thumbnail)
                        walk_thumbnail._selected = True

                    if walk_index < last_index:
                        walk_index += 1
                    else:
                        walk_index -= 1

            self.selection_mode_range = False

            if thumbnail._selected:
                self.selection_mode_last_thumbnail_index = None
                self.flowbox.unselect_child(thumbnail)
                thumbnail._selected = False
            else:
                self.selection_mode_last_thumbnail_index = thumbnail.get_index()
                thumbnail._selected = True

            if len(self.flowbox.get_selected_children()) == 0:
                self.leave_selection_mode()
        else:
            self.window.card.init(thumbnail.manga)

    def on_manga_deleted(self, manga):
        # Remove manga thumbnail in flowbox
        for thumbnail in self.flowbox.get_children():
            if thumbnail.manga.id == manga.id:
                thumbnail.destroy()
                break

    def on_manga_updated(self, _updater, manga, _nb_recent_chapters, _nb_deleted_chapters):
        for thumbnail in self.flowbox.get_children():
            if thumbnail.manga.id != manga.id:
                continue

            thumbnail.update(manga)
            break

    def on_search_entry_activate(self, _entry):
        """Open first manga in search when <Enter> is pressed"""
        thumbnail = self.flowbox.get_child_at_pos(0, 0)
        if thumbnail:
            self.on_manga_clicked(self.flowbox, thumbnail)

    def on_search_menu_action_changed(self, action, variant):
        value = variant.get_boolean()
        action.set_state(GLib.Variant('b', value))

        self.search_menu_filters[action.props.name.split('.')[-1]] = value
        if sum(self.search_menu_filters.values()):
            self.search_menu_button.get_style_context().add_class('button-warning')
        else:
            self.search_menu_button.get_style_context().remove_class('button-warning')

        self.flowbox.invalidate_filter()

    def on_selection_changed(self, _flowbox):
        number = len(self.flowbox.get_selected_children())
        if number:
            self.subtitle_label.set_label(n_('{0} selected', '{0} selected', number).format(number))
        else:
            self.subtitle_label.set_label(_('Library'))

    def on_resize(self):
        self.compute_thumbnails_size()

        if self.window.first_start_grid.is_ancestor(self.window.box):
            return

        for thumbnail in self.flowbox.get_children():
            thumbnail.resize(*self.thumbnails_size)

    def open_download_manager(self, action, param):
        DownloadManagerDialog(self.window).open(action, param)

    def populate(self):
        db_conn = create_db_connection()
        mangas_rows = db_conn.execute('SELECT * FROM mangas ORDER BY last_read DESC').fetchall()

        if len(mangas_rows) == 0:
            if self.window.overlay.is_ancestor(self.window.box):
                self.window.box.remove(self.window.overlay)

            # Display first start message
            self.window.box.add(self.window.first_start_grid)

            return

        if self.window.first_start_grid.is_ancestor(self.window):
            self.window.box.remove(self.window.first_start_grid)

        if not self.window.overlay.is_ancestor(self.window):
            self.window.box.add(self.window.overlay)

        # Clear library flowbox
        for thumbnail in self.flowbox.get_children():
            thumbnail.destroy()

        # Populate flowbox with mangas
        self.compute_thumbnails_size()
        for row in mangas_rows:
            self.add_manga(Manga.get(row['id']))

        db_conn.close()

    def search(self, _search_entry):
        self.flowbox.invalidate_filter()

    def select_all(self, _action=None, _param=None):
        if self.window.first_start_grid.is_ancestor(self.window.box):
            return

        if not self.selection_mode:
            self.enter_selection_mode()
        if not self.selection_mode:
            return

        for thumbnail in self.flowbox.get_children():
            if thumbnail._selected or thumbnail._filtered:
                continue
            thumbnail._selected = True
            self.flowbox.select_child(thumbnail)

    def show(self, invalidate_sort=False, invalidate_filter=False):
        self.window.left_button_image.set_from_icon_name('list-add-symbolic', Gtk.IconSize.MENU)

        self.search_button.show()
        self.window.card.resume_read_button.hide()
        self.window.reader.fullscreen_button.hide()

        self.window.menu_button.set_menu_model(self.builder.get_object('menu'))
        self.window.menu_button_image.set_from_icon_name('open-menu-symbolic', Gtk.IconSize.MENU)

        if self.search_mode:
            self.search_entry.grab_focus_without_selecting()

        if invalidate_sort:
            self.flowbox.invalidate_sort()

        if invalidate_filter:
            self.flowbox.invalidate_filter()

        self.window.show_page('library')

    def show_file_chooser(self, action, param):
        warning_dialog = Gtk.MessageDialog(self.window, 0, Gtk.MessageType.WARNING, Gtk.ButtonsType.YES_NO,
                                           "Try not to use this.")
        warning_dialog.format_secondary_text("Tachiyomi backups are not really compatible with how Komikku is structured. "
                                             "And as of now, there is nothing called a Komikku backup. "
                                             "So, this will not always work correctly and might result in database corruption. "
                                             "Basically, it comes with no warranty. It also requires a library update for "
                                             "the metadata to be corrected. Would you still like to continue?")
        warning_response = warning_dialog.run()
        warning_dialog.destroy()
        if warning_response == Gtk.ResponseType.YES:
            print("I'm worried for you.")
        elif warning_response in (Gtk.ResponseType.NO, Gtk.ResponseType.DELETE_EVENT, ):
            print("Good choice.")
            return False

        dialog = Gtk.FileChooserDialog(
            "Please choose your backup file", self.window,
            Gtk.FileChooserAction.OPEN,
            (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
             Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        )
        filter_json = Gtk.FileFilter()
        filter_json.set_name("Tachiyomi JSON Backup files")
        filter_json.add_mime_type("application/json")
        dialog.add_filter(filter_json)
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            import_from_file(self.window, dialog.get_filename())

            question_dialog = Gtk.MessageDialog(self.window, 0, Gtk.MessageType.QUESTION, Gtk.ButtonsType.YES_NO,
                                                "Update Library?")
            question_dialog.format_secondary_text("A library update is necessary for the manga information to correctly obtained. "
                                                  "Would you like to do the update now?")
            question_response = question_dialog.run()
            question_dialog.destroy()
            if question_response == Gtk.ResponseType.YES:
                self.window.updater.update_library()

        dialog.destroy()

        return True

    def toggle_search_mode(self, button):
        if button.get_active():
            self.search_mode = True

            self.title_stack.set_visible_child_name('searchbox')
            self.search_entry.grab_focus()
        else:
            self.search_mode = False

            self.title_stack.set_visible_child_name('title')
            self.search_entry.set_text('')
            self.search_entry.grab_remove()

    def toggle_selected_read_status(self, _action, _param, read):
        chapters_ids = []
        chapters_data = []

        self.window.activity_indicator.start()

        for thumbnail in self.flowbox.get_selected_children():
            for chapter in thumbnail.manga.chapters:
                last_page_read_index = None
                if chapter.pages:
                    pages = deepcopy(chapter.pages)
                    for page in pages:
                        page['read'] = read
                else:
                    pages = None
                    last_page_read_index = None if chapter.read == read == 0 else chapter.last_page_read_index

                chapters_ids.append(chapter.id)
                chapters_data.append(dict(
                    pages=pages,
                    read=read,
                    recent=False,
                    last_page_read_index=last_page_read_index,
                ))

        db_conn = create_db_connection()
        with db_conn:
            update_rows(db_conn, 'chapters', chapters_ids, chapters_data)
        db_conn.close()

        self.window.activity_indicator.stop()
        self.leave_selection_mode()

    def update_all(self, _action, _param):
        self.window.updater.update_library()

    def update_selected(self, _action, _param):
        self.window.updater.add([thumbnail.manga for thumbnail in self.flowbox.get_selected_children()])
        self.window.updater.start()

        self.leave_selection_mode()


class Thumbnail(Gtk.FlowBoxChild):
    def __init__(self, window, manga, width, height):
        super().__init__(visible=True)

        self.window = window
        self.manga = manga

        self._cover_pixbuf = None
        self._server_logo_pixbuf = None
        self._filtered = False
        self._selected = False

        self.overlay = Gtk.Overlay(visible=True)

        self.drawing_area = Gtk.DrawingArea(visible=True)
        self.drawing_area.connect('draw', self._draw)
        self.overlay.add(self.drawing_area)

        self.name_label = Gtk.Label(xalign=0, visible=True)
        self.name_label.get_style_context().add_class('library-manga-name-label')
        self.name_label.set_valign(Gtk.Align.END)
        self.name_label.set_line_wrap(True)
        self.overlay.add_overlay(self.name_label)

        self.add(self.overlay)
        self.resize(width, height)
        self._draw_name()

    def _draw(self, _drawing_area, context):
        context.save()

        self._draw_cover(context)
        self._draw_badges(context)
        self._draw_server_logo(context)

        context.restore()

    def _draw_badges(self, context):
        """
        Draws badges in top right corner of cover
        * Unread chapter: green
        * Recent chapters: blue
        * Downloaded chapters: red
        """
        nb_unread_chapters = self.manga.nb_unread_chapters
        nb_recent_chapters = self.manga.nb_recent_chapters
        nb_downloaded_chapters = self.manga.nb_downloaded_chapters

        if nb_unread_chapters == nb_recent_chapters == nb_downloaded_chapters == 0:
            return

        spacing = 5  # with top and right borders, between badges
        x = self.width

        context.set_font_size(13)

        def draw_badge(nb, color_r, color_g, color_b):
            nonlocal x

            if nb == 0:
                return

            text = str(nb)
            text_extents = context.text_extents(text)
            width = text_extents.x_advance + 2 * 3 + 1
            height = text_extents.height + 2 * 5

            # Draw rectangle
            x = x - spacing - width
            context.set_source_rgb(color_r, color_g, color_b)
            context.rectangle(x, spacing, width, height)
            context.fill()

            # Draw number
            context.set_source_rgb(1, 1, 1)
            context.move_to(x + 3, height)
            context.show_text(text)

        draw_badge(nb_unread_chapters, 0.2, 0.5, 0)        # #338000
        draw_badge(nb_recent_chapters, 0.2, 0.6, 1)        # #3399FF
        draw_badge(nb_downloaded_chapters, 1, 0.266, 0.2)  # #FF4433

    def _draw_cover(self, context):
        if self._cover_pixbuf is None:
            if self.manga.cover_fs_path is None:
                self._cover_pixbuf = Pixbuf.new_from_resource('/info/febvre/Komikku/images/missing_file.png')
            else:
                try:
                    if get_file_mime_type(self.manga.cover_fs_path) != 'image/gif':
                        self._cover_pixbuf = Pixbuf.new_from_file_at_scale(self.manga.cover_fs_path, 200, -1, True)
                    else:
                        animation_pixbuf = scale_pixbuf_animation(PixbufAnimation.new_from_file(self.manga.cover_fs_path), 200, -1, True)
                        self._cover_pixbuf = animation_pixbuf.get_static_image()
                except Exception:
                    # Invalid image, corrupted image, unsupported image format,...
                    self._cover_pixbuf = Pixbuf.new_from_resource('/info/febvre/Komikku/images/missing_file.png')

        pixbuf = self._cover_pixbuf.scale_simple(
            self.width * self.window.hidpi_scale, self.height * self.window.hidpi_scale, InterpType.BILINEAR)

        radius = 6
        arc_0 = 0
        arc_1 = math.pi * 0.5
        arc_2 = math.pi
        arc_3 = math.pi * 1.5

        context.new_sub_path()
        context.arc(self.width - radius, radius, radius, arc_3, arc_0)
        context.arc(self.width - radius, self.height - radius, radius, arc_0, arc_1)
        context.arc(radius, self.height - radius, radius, arc_1, arc_2)
        context.arc(radius, radius, radius, arc_2, arc_3)
        context.close_path()

        context.clip()

        context.scale(1 / self.window.hidpi_scale, 1 / self.window.hidpi_scale)

        Gdk.cairo_set_source_pixbuf(context, pixbuf, 0, 0)
        context.paint()

    def _draw_name(self):
        self.name_label.set_text(self.manga.name)

    def _draw_server_logo(self, context):
        if self._server_logo_pixbuf is None:
            logo_path = self.manga.server.logo_path
            if logo_path is not None:
                self._server_logo_pixbuf = Pixbuf.new_from_file_at_scale(
                    logo_path, 20 * self.window.hidpi_scale, 20 * self.window.hidpi_scale, True)
            else:
                self._server_logo_pixbuf = 0

        if self._server_logo_pixbuf:
            surface = Gdk.cairo_surface_create_from_pixbuf(self._server_logo_pixbuf, self.window.hidpi_scale)
            context.set_source_surface(surface, 4, 4)
            context.paint()

    def resize(self, width, height):
        self.width = width
        self.height = height

        self.drawing_area.set_size_request(self.width, self.height)

    def update(self, manga):
        self.manga = manga
        self._cover_pixbuf = None

        self._draw_name()
        # Schedule a redraw to update drawing areas (cover, server logo and badges)
        self.queue_draw()
