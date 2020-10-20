# Copyright (C) 2019-2020 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from abc import abstractmethod
import datetime
from gettext import gettext as _

from gi.repository import Gdk
from gi.repository import GLib
from gi.repository import Gtk
from gi.repository import Handy
from gi.repository.GdkPixbuf import InterpType

from komikku.reader.pager.page import Page


class BasePager:
    btn_press_handler_id = None
    btn_press_timeout_id = None
    key_press_handler_id = None
    default_double_click_time = Gtk.Settings.get_default().get_property('gtk-double-click-time')
    zoom = dict(active=False)

    def __init__(self, reader):
        self.reader = reader
        self.window = reader.window

        self.scrolledwindow = self.reader.scrolledwindow
        self.scrolledwindow.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK |
            Gdk.EventMask.BUTTON_RELEASE_MASK |
            Gdk.EventMask.KEY_PRESS_MASK |
            Gdk.EventMask.SMOOTH_SCROLL_MASK
        )
        self.scrolledwindow.set_kinetic_scrolling(True)
        self.scrolledwindow.set_overlay_scrolling(True)
        self.scrolledwindow.get_hscrollbar().hide()
        self.scrolledwindow.get_vscrollbar().hide()

        self.connect('motion-notify-event', self.on_motion_notify)

    @property
    @abstractmethod
    def pages(self):
        return self.get_children()

    @abstractmethod
    def add_page(self, position):
        raise NotImplementedError()

    def clear(self):
        self.disable_keyboard_and_mouse_click_navigation()

        for page in self.pages:
            page.clean()
            page.destroy()

    def crop_pages_borders(self):
        for page in self.pages:
            if page.status == 'rendered' and page.error is None:
                page.set_image()

    def disable_keyboard_and_mouse_click_navigation(self):
        # Keyboard
        if self.key_press_handler_id:
            self.window.disconnect(self.key_press_handler_id)
            self.key_press_handler_id = None

        # Mouse click
        if self.btn_press_handler_id:
            self.scrolledwindow.disconnect(self.btn_press_handler_id)
            self.btn_press_handler_id = None

    def enable_keyboard_and_mouse_click_navigation(self):
        # Keyboard
        if self.key_press_handler_id is None:
            self.key_press_handler_id = self.window.connect('key-press-event', self.on_key_press)

        # Mouse click
        if self.btn_press_handler_id is None:
            self.btn_press_handler_id = self.scrolledwindow.connect('button-press-event', self.on_btn_press)

    @abstractmethod
    def goto_page(self, page_index):
        raise NotImplementedError()

    def hide_cursor(self):
        self.get_window().set_cursor(Gdk.Cursor.new_from_name(Gdk.Display.get_default(), 'none'))

    @abstractmethod
    def init(self):
        raise NotImplementedError()

    def on_btn_press(self, widget, event):
        if event.button == 1:
            if self.btn_press_timeout_id is None and event.type == Gdk.EventType.BUTTON_PRESS:
                # Schedule single click event to be able to detect double click
                self.btn_press_timeout_id = GLib.timeout_add(self.default_double_click_time + 100, self.on_single_click, event.copy())

            elif event.type == Gdk.EventType._2BUTTON_PRESS:
                # Remove scheduled single click event
                if self.btn_press_timeout_id:
                    GLib.source_remove(self.btn_press_timeout_id)
                    self.btn_press_timeout_id = None

                GLib.idle_add(self.on_double_click, event.copy())

        return Gdk.EVENT_STOP

    def on_double_click(self, event):
        # Zoom/unzoom
        if self.reader.reading_mode == 'webtoon':
            return

        def on_adjustment_change(hadj, vadj, h_value, v_value):
            hadj.disconnect(handler_id)

            def adjust_scroll():
                hadj.set_value(h_value)
                vadj.set_value(v_value)

            GLib.idle_add(adjust_scroll)

        page = self.current_page

        if page.status != 'rendered' or page.error is not None or page.animated:
            return

        hadj = page.scrolledwindow.get_hadjustment()
        vadj = page.scrolledwindow.get_vadjustment()

        if self.zoom['active'] is False:
            self.set_interactive(False)

            image = page.image
            pixbuf = page.imagebuf.get_pixbuf()

            # Record hadjustment and vadjustment values
            self.zoom['orig_hadj_value'] = hadj.get_value()
            self.zoom['orig_vadj_value'] = vadj.get_value()

            # Adjust image's width to 2x window's width
            factor = 2
            orig_width = page.surface.get_width() / self.window.hidpi_scale
            orig_height = page.surface.get_height() / self.window.hidpi_scale
            zoom_width = self.reader.size.width * factor
            zoom_height = orig_height * (zoom_width / orig_width)
            ratio = zoom_width / orig_width

            if orig_width <= self.reader.size.width:
                rel_event_x = event.x - (self.reader.size.width - orig_width) / 2
            else:
                rel_event_x = event.x + hadj.get_value()
            if orig_height <= self.reader.size.height:
                rel_event_y = event.y - (self.reader.size.height - orig_height) / 2
            else:
                rel_event_y = event.y + vadj.get_value()

            h_value = rel_event_x * ratio - event.x
            v_value = rel_event_y * ratio - event.y

            handler_id = hadj.connect('changed', on_adjustment_change, vadj, h_value, v_value)

            scaled_pixbuf = pixbuf.scale_simple(
                zoom_width * self.window.hidpi_scale, zoom_height * self.window.hidpi_scale, InterpType.BILINEAR)

            image.set_from_surface(Gdk.cairo_surface_create_from_pixbuf(scaled_pixbuf, self.window.hidpi_scale))

            self.zoom['active'] = True
        else:
            self.set_interactive(True)

            handler_id = hadj.connect(
                'changed', on_adjustment_change, vadj, self.zoom['orig_hadj_value'], self.zoom['orig_vadj_value'])

            page.set_image()

            self.zoom['active'] = False

    @abstractmethod
    def on_key_press(self, _widget, event):
        raise NotImplementedError()

    def on_motion_notify(self, widget, event):
        if self.get_window().get_cursor():
            # Cursor is hidden during keyboard navigation
            # Make cursor visible again when mouse is moved
            self.show_cursor()

        return Gdk.EVENT_PROPAGATE

    def on_page_rendered(self, page, retry):
        if not retry:
            return

        GLib.idle_add(self.update, page, 1)
        GLib.idle_add(self.save_progress, page)

    def on_single_click(self, event):
        self.btn_press_timeout_id = None

        if event.x < self.reader.size.width / 3:
            # 1st third of the page
            if self.zoom['active']:
                return False

            self.scroll_to_direction('left')
        elif event.x > 2 * self.reader.size.width / 3:
            # Last third of the page
            if self.zoom['active']:
                return False

            self.scroll_to_direction('right')
        else:
            # Center part of the page: toggle controls
            self.reader.toggle_controls()

        return False

    def rescale_pages(self):
        self.zoom['active'] = False

        for page in self.pages:
            page.rescale()

    def resize_pages(self, _pager=None, _orientation=None):
        self.zoom['active'] = False

        for page in self.pages:
            page.resize()

    def save_progress(self, page):
        """Save reading progress"""

        if page not in self.pages:
            return GLib.SOURCE_REMOVE

        # Loop as long as the page rendering is not ended
        if page.status == 'rendering':
            return GLib.SOURCE_CONTINUE

        if page.status != 'rendered' or page.error is not None:
            return GLib.SOURCE_REMOVE

        chapter = page.chapter

        # Update manga last read time
        self.reader.manga.update(dict(last_read=datetime.datetime.now()))

        # Mark page as read
        chapter.pages[page.index]['read'] = True

        # Check if chapter has been fully read
        chapter_is_read = True
        for chapter_page in reversed(chapter.pages):
            if not chapter_page.get('read'):
                chapter_is_read = False
                break

        # Update chapter
        chapter.update(dict(
            pages=chapter.pages,
            last_page_read_index=page.index,
            read=chapter_is_read,
            recent=0,
        ))

        return GLib.SOURCE_REMOVE

    @abstractmethod
    def scroll_to_direction(self, direction):
        raise NotImplementedError()

    def show_cursor(self):
        # Restore the default cursor
        self.get_window().set_cursor(None)


class Pager(Handy.Carousel, BasePager):
    """Classic page by page pager (LTR, RTL, vertical)"""

    current_chapter_id = None
    init_flag = False

    def __init__(self, reader):
        Handy.Carousel.__init__(self)
        BasePager.__init__(self, reader)

        self.set_animation_duration(500)
        self.set_allow_mouse_drag(False)

        self.connect('notify::orientation', self.resize_pages)
        self.connect('page-changed', self.on_page_changed)

    @property
    def current_page(self):
        return self.pages[int(self.get_position())] if len(self.pages) == 3 else None

    def add_page(self, position):
        if position == 'start':
            self.pages[2].clean()
            self.pages[2].destroy()  # will remove it from carousel

            page = self.pages[0]
            direction = 1 if self.reader.reading_mode == 'right-to-left' else -1
            new_page = Page(self, page.chapter, page.index + direction)
            self.prepend(new_page)
        else:
            self.pages[0].clean()
            self.pages[0].destroy()  # will remove it from carousel

            page = self.pages[-1]
            direction = -1 if self.reader.reading_mode == 'right-to-left' else 1
            new_page = Page(self, page.chapter, page.index + direction)
            self.insert(new_page, 2)

        new_page.connect('rendered', self.on_page_rendered)
        new_page.render()

    def goto_page(self, index):
        if self.pages[0].index == index and self.pages[0].chapter == self.current_page.chapter:
            self.scroll_to_direction('left')
        elif self.pages[2].index == index and self.pages[2].chapter == self.current_page.chapter:
            self.scroll_to_direction('right')
        else:
            self.init(self.current_page.chapter, index)

    def init(self, chapter, page_index=None):
        self.init_flag = True
        self.zoom['active'] = False

        self.reader.update_title(chapter)
        self.clear()

        if page_index is None:
            if chapter.read:
                page_index = 0
            elif chapter.last_page_read_index is not None:
                page_index = chapter.last_page_read_index
            else:
                page_index = 0

        direction = 1 if self.reader.reading_mode == 'right-to-left' else -1

        # Left page
        left_page = Page(self, chapter, page_index + direction)
        left_page.connect('rendered', self.on_page_rendered)
        self.insert(left_page, 0)

        # Center page
        center_page = Page(self, chapter, page_index)
        center_page.connect('rendered', self.on_page_rendered)
        self.insert(center_page, 1)
        center_page.render()

        # Right page
        right_page = Page(self, chapter, page_index - direction)
        right_page.connect('rendered', self.on_page_rendered)
        self.insert(right_page, 2)

        left_page.render()
        right_page.render()

        self.scroll_to(center_page)

    def on_key_press(self, _widget, event):
        if self.window.page != 'reader':
            return Gdk.EVENT_PROPAGATE

        modifiers = Gtk.accelerator_get_default_mod_mask()
        if (event.state & modifiers) != 0:
            return Gdk.EVENT_PROPAGATE

        if event.keyval in (Gdk.KEY_Left, Gdk.KEY_KP_Left, Gdk.KEY_Right, Gdk.KEY_KP_Right):
            # Hide mouse cursor when using keyboard navigation
            self.hide_cursor()

            page = self.current_page
            hadj = page.scrolledwindow.get_hadjustment()

            if event.keyval in (Gdk.KEY_Left, Gdk.KEY_KP_Left):
                if hadj.get_value() == 0 and self.zoom['active'] is False:
                    self.scroll_to_direction('left')
                    return Gdk.EVENT_STOP

                page.scrolledwindow.emit('scroll-child', Gtk.ScrollType.STEP_LEFT, False)
                return Gdk.EVENT_STOP

            if hadj.get_value() + self.reader.size.width == hadj.get_upper() and self.zoom['active'] is False:
                self.scroll_to_direction('right')
                return Gdk.EVENT_STOP

            page.scrolledwindow.emit('scroll-child', Gtk.ScrollType.STEP_RIGHT, False)
            return Gdk.EVENT_STOP

        if event.keyval in (Gdk.KEY_Up, Gdk.KEY_KP_Up, Gdk.KEY_Down, Gdk.KEY_KP_Down):
            # Hide mouse cursor when using keyboard navigation
            self.hide_cursor()

            page = self.current_page
            vadj = page.scrolledwindow.get_vadjustment()

            if event.keyval in (Gdk.KEY_Down, Gdk.KEY_KP_Down):
                if self.reader.reading_mode == 'vertical' and vadj.get_value() + self.reader.size.height == vadj.get_upper():
                    self.scroll_to_direction('right')
                    return Gdk.EVENT_STOP

                # If image height is greater than viewport height, arrow keys should scroll page down
                # Emit scroll signal: one step down
                page.scrolledwindow.emit('scroll-child', Gtk.ScrollType.STEP_DOWN, False)
                return Gdk.EVENT_STOP

            if self.reader.reading_mode == 'vertical' and vadj.get_value() == 0:
                self.scroll_to_direction('left')

                # After switching pages, go to the end of the page that is now the current page
                vadj = self.current_page.scrolledwindow.get_vadjustment()
                vadj.set_value(vadj.get_upper() - self.reader.size.height)
                return Gdk.EVENT_STOP

            # If image height is greater than viewport height, arrow keys should scroll page up
            # Emit scroll signal: one step up
            page.scrolledwindow.emit('scroll-child', Gtk.ScrollType.STEP_UP, False)
            return Gdk.EVENT_STOP

        return Gdk.EVENT_PROPAGATE

    def on_page_changed(self, carousel, index):
        if self.pages[1].cropped:
            # Previous page's image has been cropped to allow 2-fingers swipe gesture, it must be restored
            self.pages[1].set_image()

        if index == 1 and not self.init_flag:
            # Partial swipe gesture
            return

        self.init_flag = False
        page = self.pages[index]

        if page.status == 'offlimit':
            GLib.idle_add(self.scroll_to, self.pages[1])

            if page.index == -1:
                message = _('There is no previous chapter.')
            else:
                message = _('It was the last chapter.')
            self.window.show_notification(message, interval=2)

            return

        # Disable navigation: will be re-enabled if page is loadable
        self.disable_keyboard_and_mouse_click_navigation()
        self.set_interactive(False)

        GLib.idle_add(self.update, page, index)
        GLib.idle_add(self.save_progress, page)

    def reverse_pages(self):
        self.reorder(self.pages[0], -1)
        self.reorder(self.pages[0], 1)

    def scroll_to_direction(self, direction):
        if direction == 'left':
            page = self.pages[0]
        elif direction == 'right':
            page = self.pages[-1]

        if page.status == 'offlimit':
            # We reached first or last chapter
            if direction == 'left':
                message = _('It was the last chapter.')
            elif direction == 'right':
                message = _('There is no previous chapter.')
            self.window.show_notification(message, interval=2)

            return

        if page == self.current_page:
            # Can occur during a quick keyboard navigation (when holding down an arrow key)
            return

        # Disable keyboard and mouse navigation: will be re-enabled if page is loadable
        self.disable_keyboard_and_mouse_click_navigation()

        self.scroll_to(page)

    def update(self, page, index):
        if not page.loadable and page.error is None:
            # Loop until page is loadable or page is on error
            return GLib.SOURCE_CONTINUE

        if page.loadable:
            self.enable_keyboard_and_mouse_click_navigation()
            self.set_interactive(True)

            if index != 1:
                # Add next page depending of navigation direction
                self.add_page('start' if index == 0 else 'end')
        elif page.index == 0:
            self.window.show_notification(_('This chapter is inaccessible.'), 2)

        # Update title, initialize controls and notify user if chapter changed
        if self.current_chapter_id != page.chapter.id:
            self.current_chapter_id = page.chapter.id
            self.reader.update_title(page.chapter)
            self.window.show_notification(page.chapter.title, 2)
            self.reader.controls.init(page.chapter)

        # Update page number and controls page slider
        if page.chapter.pages:
            self.reader.update_page_number(page.index + 1, len(page.chapter.pages) if page.loadable else None)
            self.reader.controls.set_scale_value(page.index + 1)

        return GLib.SOURCE_REMOVE
