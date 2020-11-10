# Copyright (C) 2019-2020 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import datetime
from gettext import gettext as _
from gettext import ngettext as n_
import threading
import time

from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gtk
from gi.repository import Notify

from komikku.models import Chapter
from komikku.models import create_db_connection
from komikku.models import Download
from komikku.models import insert_rows
from komikku.models import Settings
from komikku.utils import log_error_traceback

DOWNLOAD_DELAY = 1  # in seconds


class Downloader(GObject.GObject):
    """ Chapters downloader """
    __gsignals__ = {
        'download-changed': (GObject.SIGNAL_RUN_FIRST, None, (GObject.TYPE_PYOBJECT, GObject.TYPE_PYOBJECT, )),
        'ended': (GObject.SIGNAL_RUN_FIRST, None, ()),
        'started': (GObject.SIGNAL_RUN_FIRST, None, ()),
    }

    running = False
    stop_flag = False

    def __init__(self, window):
        GObject.GObject.__init__(self)

        self.window = window
        if Settings.get_default().downloader_state:
            self.start()

    def add(self, chapters, emit_signal=False):
        chapters_ids = []
        rows_data = []

        for chapter in chapters:
            if isinstance(chapter, Chapter):
                if chapter.downloaded:
                    continue
                chapter_id = chapter.id
            else:
                chapter_id = chapter

            rows_data.append(dict(
                chapter_id=chapter_id,
                status='pending',
                percent=0,
                date=datetime.datetime.now(),
            ))
            chapters_ids.append(chapter_id)

        if not chapters_ids:
            return

        db_conn = create_db_connection()
        with db_conn:
            insert_rows(db_conn, 'downloads', rows_data)
        db_conn.close()

        if emit_signal:
            for chapter_id in chapters_ids:
                download = Download.get_by_chapter_id(chapter_id)
                if download:
                    self.emit('download-changed', download, None)

    def remove(self, chapters):
        if not isinstance(chapters, list):
            chapters = [chapters, ]

        was_running = self.running

        self.stop()

        while self.running:
            time.sleep(0.1)
            continue

        for chapter in chapters:
            download = Download.get_by_chapter_id(chapter.id)
            if download:
                download.delete()

            self.emit('download-changed', None, chapter)

        if was_running:
            self.start()

    def start(self):
        def run(exclude_errors=False):
            db_conn = create_db_connection()
            if exclude_errors:
                rows = db_conn.execute('SELECT * FROM downloads WHERE status != "error" ORDER BY date ASC').fetchall()
            else:
                rows = db_conn.execute('SELECT * FROM downloads ORDER BY date ASC').fetchall()
            db_conn.close()

            interrupted = False
            for row in rows:
                if self.stop_flag:
                    break

                download = Download.get(row['id'])
                if download is None:
                    # Download has been removed in the meantime
                    continue

                chapter = download.chapter

                download.update(dict(status='downloading'))
                GLib.idle_add(notify_download_started, download)

                try:
                    if chapter.update_full() and len(chapter.pages) > 0:
                        error_counter = 0
                        success_counter = 0
                        for index, _page in enumerate(chapter.pages):
                            if self.stop_flag:
                                interrupted = True
                                break

                            if chapter.get_page_path(index) is None:
                                path = chapter.get_page(index)
                                if path is not None:
                                    success_counter += 1
                                    download.update(dict(percent=(index + 1) * 100 / len(chapter.pages)))
                                else:
                                    error_counter += 1
                                    download.update(dict(errors=error_counter))

                                GLib.idle_add(notify_download_progress, download, success_counter, error_counter)

                                if index < len(chapter.pages) - 1 and not self.stop_flag:
                                    time.sleep(DOWNLOAD_DELAY)
                            else:
                                success_counter += 1

                        if interrupted:
                            download.update(dict(status='pending'))
                        else:
                            if error_counter == 0:
                                # All pages were successfully downloaded
                                chapter.update(dict(downloaded=1))
                                download.delete()
                                GLib.idle_add(notify_download_success, chapter)
                            else:
                                # At least one page failed to be downloaded
                                download.update(dict(status='error'))
                                GLib.idle_add(notify_download_error, download)
                    else:
                        # Possible causes:
                        # - Empty chapter
                        # - Outdated chapter info
                        # - Server has undergone changes (API, HTML) and plugin code is outdated
                        download.update(dict(status='error'))
                        GLib.idle_add(notify_download_error, download)
                except Exception as e:
                    # Possible causes:
                    # - No Internet connection
                    # - Connexion timeout, read timeout
                    # - Server down
                    download.update(dict(status='error'))
                    user_error_message = log_error_traceback(e)
                    GLib.idle_add(notify_download_error, download, user_error_message)

            if not rows or self.stop_flag:
                self.running = False
                GLib.idle_add(self.emit, 'ended')
            else:
                # Continue, new downloads may have been added in the meantime
                run(exclude_errors=True)

        def notify_download_success(chapter):
            if notification is not None:
                notification.update(
                    _('Download completed'),
                    _('[{0}] Chapter {1}').format(chapter.manga.name, chapter.title)
                )
                notification.show()

            self.emit('download-changed', None, chapter)

            return False

        def notify_download_error(download, message=None):
            if message:
                self.window.show_notification(f'[{download.chapter.manga.name}] Chapter {download.chapter.title}'
                                              f'\nDownload failed. Please try again.\n{message}')

            self.emit('download-changed', download, None)

            return False

        def notify_download_started(download):
            self.emit('download-changed', download, None)

            return False

        def notify_download_progress(download, success_counter, error_counter):
            if notification is not None:
                summary = _('{0}/{1} pages downloaded').format(success_counter, len(download.chapter.pages))
                if error_counter > 0:
                    summary = '{0} ({1})'.format(summary, _('error'))

                notification.update(
                    summary,
                    _('[{0}] Chapter {1}').format(download.chapter.manga.name, download.chapter.title)
                )
                notification.show()

            self.emit('download-changed', download, None)

            return False

        if self.running:
            return

        Settings.get_default().downloader_state = True
        self.running = True
        self.stop_flag = False

        if Settings.get_default().desktop_notifications:
            # Create notification
            notification = Notify.Notification.new('')
            notification.set_timeout(Notify.EXPIRES_DEFAULT)
        else:
            notification = None

        GLib.idle_add(self.emit, 'started')

        thread = threading.Thread(target=run)
        thread.daemon = True
        thread.start()

    def stop(self, save_state=False):
        if self.running:
            self.stop_flag = True
            if save_state:
                Settings.get_default().downloader_state = False


@Gtk.Template.from_resource('/info/febvre/Komikku/ui/download_manager_dialog.ui')
class DownloadManagerDialog(Gtk.Dialog):
    __gtype_name__ = 'DownloadManagerDialog'
    __gsignals_handlers_ids__ = None

    selection_mode = False
    selection_mode_count = 0
    selection_mode_range = False
    selection_mode_last_row_index = None

    titlebar = Gtk.Template.Child('titlebar')
    back_button = Gtk.Template.Child('back_button')
    subtitle_label = Gtk.Template.Child('subtitle_label')
    start_stop_button = Gtk.Template.Child('start_stop_button')
    start_stop_button_image = Gtk.Template.Child('start_stop_button_image')
    menu_button = Gtk.Template.Child('menu_button')
    stack = Gtk.Template.Child('stack')
    listbox = Gtk.Template.Child('listbox')

    def __init__(self, window):
        Gtk.Dialog.__init__(self)

        self.set_titlebar(self.titlebar)
        self.set_transient_for(window)

        self.builder = window.builder
        self.builder.add_from_resource('/info/febvre/Komikku/ui/menu/download_manager.xml')
        self.builder.add_from_resource('/info/febvre/Komikku/ui/menu/download_manager_selection_mode.xml')

        self.downloader = window.downloader

        self.connect('key-press-event', self.on_key_press_event)
        self.back_button.connect('clicked', self.on_back_button_clicked)
        self.start_stop_button.connect('clicked', self.on_start_stop_button_clicked)
        self.menu_button.set_menu_model(self.builder.get_object('menu-download-manager'))
        self.listbox.connect('button-press-event', self.on_button_pressed)
        self.listbox.connect('row-activated', self.on_download_row_clicked)
        self.listbox.connect('selected-rows-changed', self.on_selection_changed)

        # Gesture for multi-selection mode
        self.gesture = Gtk.GestureLongPress.new(self.listbox)
        self.gesture.set_touch_only(False)
        self.gesture.connect('pressed', self.on_gesture_long_press_activated)

        self.__gsignals_handlers_ids__ = [
            self.downloader.connect('download-changed', self.update_row),
            self.downloader.connect('ended', self.update_headerbar),
            self.downloader.connect('started', self.update_headerbar),
        ]

        action_group = Gio.SimpleActionGroup.new()

        # Delete All action
        delete_all_action = Gio.SimpleAction.new('delete-all', None)
        delete_all_action.connect('activate', self.on_menu_delete_all_clicked)
        action_group.add_action(delete_all_action)

        # Delete Selected action
        delete_selected_action = Gio.SimpleAction.new('delete-selected', None)
        delete_selected_action.connect('activate', self.on_menu_delete_selected_clicked)
        action_group.add_action(delete_selected_action)

        self.insert_action_group('download-manager', action_group)

    @property
    def rows(self):
        return self.listbox.get_children()

    def close(self):
        # Disconnect from signals
        for handler_id in self.__gsignals_handlers_ids__:
            self.downloader.disconnect(handler_id)

        self.destroy()

    def enter_selection_mode(self):
        self.selection_mode = True
        self.selection_mode_count = 0

        self.listbox.set_selection_mode(Gtk.SelectionMode.MULTIPLE)

        self.titlebar.set_selection_mode(True)
        self.menu_button.set_menu_model(self.builder.get_object('menu-download-manager-selection-mode'))

    def leave_selection_mode(self):
        self.selection_mode = False

        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        for row in self.rows:
            row._selected = False

        self.titlebar.set_selection_mode(False)
        self.menu_button.set_menu_model(self.builder.get_object('menu-download-manager'))

    def on_back_button_clicked(self, button=None):
        if self.selection_mode:
            self.leave_selection_mode()
        else:
            self.close()

    def on_button_pressed(self, _widget, event):
        row = self.listbox.get_row_at_y(event.y)
        if not self.selection_mode and event.type == Gdk.EventType.BUTTON_PRESS and event.button == 3 and row is not None:
            self.enter_selection_mode()
            self.on_download_row_clicked(None, row)
            return Gdk.EVENT_STOP

        return Gdk.EVENT_PROPAGATE

    def on_download_row_clicked(self, listbox, row):
        _ret, state = Gtk.get_current_event_state()
        modifiers = Gtk.accelerator_get_default_mod_mask()

        # Enter selection mode if <Control>+Click or <Shift>+Click is done
        if state & modifiers in (Gdk.ModifierType.CONTROL_MASK, Gdk.ModifierType.SHIFT_MASK) and not self.selection_mode:
            self.enter_selection_mode()

        if not self.selection_mode:
            return

        if state & modifiers == Gdk.ModifierType.SHIFT_MASK:
            # Enter range selection mode if <Shift>+Click is done
            self.selection_mode_range = True

        if self.selection_mode_range and self.selection_mode_last_row_index is not None:
            # Range selection mode: select all rows between last selected row and clicked row
            walk_index = self.selection_mode_last_row_index
            last_index = row.get_index()

            while walk_index != last_index:
                walk_row = self.listbox.get_row_at_index(walk_index)
                if walk_row and not walk_row._selected:
                    self.selection_mode_count += 1
                    self.listbox.select_row(walk_row)
                    walk_row._selected = True

                if walk_index < last_index:
                    walk_index += 1
                else:
                    walk_index -= 1

        self.selection_mode_range = False

        if row._selected:
            self.selection_mode_count -= 1
            self.listbox.unselect_row(row)
            self.selection_mode_last_row_index = None
            row._selected = False
        else:
            self.selection_mode_count += 1
            self.listbox.select_row(row)
            self.selection_mode_last_row_index = row.get_index()
            row._selected = True

        if self.selection_mode_count == 0:
            self.leave_selection_mode()

    def on_gesture_long_press_activated(self, gesture, x, y):
        if self.selection_mode:
            # Enter in 'Range' selection mode
            # Long press on a download row then long press on another to select everything in between
            self.selection_mode_range = True
        else:
            self.enter_selection_mode()

    def on_key_press_event(self, widget, event):
        modifiers = event.get_state() & Gtk.accelerator_get_default_mod_mask()

        # <Control>+Key
        if modifiers == Gdk.ModifierType.CONTROL_MASK:
            # <Control>+A (select all)
            if event.keyval in (Gdk.KEY_a, Gdk.KEY_A):
                self.select_all()
                return Gdk.EVENT_STOP

        return Gdk.EVENT_PROPAGATE

    def on_menu_delete_all_clicked(self, action, param):
        chapters = []
        for row in self.rows:
            chapters.append(row.download.chapter)
            row.destroy()

        self.downloader.remove(chapters)

        self.leave_selection_mode()
        self.update_headerbar()
        GLib.idle_add(self.stack.set_visible_child_name, 'empty')

    def on_menu_delete_selected_clicked(self, action, param):
        chapters = []
        for row in self.rows:
            if row._selected:
                chapters.append(row.download.chapter)
                row.destroy()

        self.downloader.remove(chapters)

        self.leave_selection_mode()
        self.update_headerbar()
        if not self.rows:
            GLib.idle_add(self.stack.set_visible_child_name, 'empty')

    def on_selection_changed(self, _flowbox):
        number = len(self.listbox.get_selected_rows())
        if number:
            self.subtitle_label.set_label(n_('{0} selected', '{0} selected', number).format(number))
            self.subtitle_label.show()
        else:
            self.subtitle_label.hide()

    def on_start_stop_button_clicked(self, button):
        self.start_stop_button.set_sensitive(False)

        if self.downloader.running:
            self.downloader.stop(save_state=True)
        else:
            self.downloader.start()

    def open(self, action, param):
        self.populate()
        self.update_headerbar()

        if self.run() in (Gtk.ResponseType.CANCEL, Gtk.ResponseType.DELETE_EVENT, ):
            self.on_back_button_clicked()

    def populate(self):
        db_conn = create_db_connection()
        records = db_conn.execute('SELECT * FROM downloads ORDER BY date ASC').fetchall()
        db_conn.close()

        if records:
            for record in records:
                download = Download.get(record['id'])

                row = DownloadRow(download)
                self.listbox.add(row)

            self.listbox.show_all()
            self.stack.set_visible_child_name('list')
        else:
            self.stack.set_visible_child_name('empty')

    def select_all(self):
        if not self.selection_mode:
            self.enter_selection_mode()

        self.selection_mode_count = len(self.listbox.get_children())

        for row in self.listbox.get_children():
            if row._selected:
                continue
            self.listbox.select_row(row)
            row._selected = True

    def update_headerbar(self, *args):
        if self.rows:
            if self.downloader.running:
                self.start_stop_button_image.set_from_icon_name('media-playback-stop-symbolic', Gtk.IconSize.MENU)
            else:
                self.start_stop_button_image.set_from_icon_name('media-playback-start-symbolic', Gtk.IconSize.MENU)

            self.start_stop_button.set_sensitive(True)
            self.start_stop_button.show()
            self.menu_button.show()
        else:
            self.start_stop_button.hide()
            self.menu_button.hide()

    def update_row(self, downloader, download, chapter):
        chapter_id = chapter.id if chapter is not None else download.chapter.id

        for row in self.rows:
            if row.download.chapter.id == chapter_id:
                row.download = download
                if row.download:
                    row.update()
                else:
                    row.destroy()
                break

        if not self.rows:
            self.stack.set_visible_child_name('empty')


class DownloadRow(Gtk.ListBoxRow):
    _selected = False

    def __init__(self, download):
        Gtk.ListBoxRow.__init__(self)

        self.get_style_context().add_class('download-manager-download-listboxrow')

        self.download = download

        if self.download.percent:
            nb_pages = len(download.chapter.pages)
            counter = int((nb_pages / 100) * self.download.percent)
            fraction = self.download.percent / 100
        else:
            counter = None
            fraction = None

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        # Manga
        label = Gtk.Label(xalign=0)
        label.get_style_context().add_class('download-manager-download-label')
        label.set_valign(Gtk.Align.CENTER)
        label.set_line_wrap(True)
        label.set_text(download.chapter.manga.name)
        hbox.pack_start(label, True, True, 0)

        # Progress label
        self.progress_label = Gtk.Label(xalign=0)
        self.progress_label.get_style_context().add_class('download-manager-download-sublabel')
        self.progress_label.set_valign(Gtk.Align.CENTER)
        self.progress_label.set_line_wrap(True)
        text = _(Download.STATUSES[self.download.status]).upper() if self.download.status == 'error' else ''
        if counter:
            text = f'{text} {counter}/{nb_pages}'
        if text:
            self.progress_label.set_text(text)
        hbox.pack_start(self.progress_label, False, False, 0)

        vbox.pack_start(hbox, True, True, 0)

        # Chapter
        label = Gtk.Label(xalign=0)
        label.get_style_context().add_class('download-manager-download-sublabel')
        label.set_valign(Gtk.Align.CENTER)
        label.set_line_wrap(True)
        label.set_text(download.chapter.title)
        vbox.pack_start(label, True, True, 0)

        # Progress bar
        self.progressbar = Gtk.ProgressBar()
        self.progressbar.set_show_text(False)
        if fraction:
            self.progressbar.set_fraction(fraction)
        vbox.pack_start(self.progressbar, True, True, 0)

        self.add(vbox)

    def update(self):
        """ Updates chapter download progress """
        if not self.download.chapter.pages:
            return

        nb_pages = len(self.download.chapter.pages)
        counter = int((nb_pages / 100) * self.download.percent)
        fraction = self.download.percent / 100

        self.progressbar.set_fraction(fraction)
        text = _(Download.STATUSES[self.download.status]).upper() if self.download.status == 'error' else ''
        text = f'{text} {counter}/{nb_pages}'
        self.progress_label.set_text(text)
