import datetime
import threading

from gi.repository import Gdk
from gi.repository import GLib
from gi.repository import Gtk
from gi.repository.GdkPixbuf import InterpType
from gi.repository.GdkPixbuf import Pixbuf

from mangascan.model import create_db_connection
from mangascan.model import Chapter


class Reader():
    chapter = None
    pixbuf = None
    size = None

    def __init__(self, window):
        self.window = window
        self.builder = window.builder

        self.viewport = self.builder.get_object('reader_page_viewport')
        self.scrolledwindow = self.viewport.get_parent()
        self.overlay = self.scrolledwindow.get_parent()

        self.image = Gtk.Image()
        self.viewport.add(self.image)

        self.spinner_box = self.builder.get_object('spinner_box')
        self.overlay.add_overlay(self.spinner_box)
        self.hide_spinner()

        self.window.connect('check-resize', self.on_resize)
        self.scrolledwindow.connect('button-press-event', self.on_button_press)

    def hide_spinner(self):
        self.spinner_box.hide()
        self.spinner_box.get_children()[0].stop()

    def init(self, chapter, index=None):
        def run():
            self.chapter.update()

            GLib.idle_add(complete, index)

        def complete(index):
            self.chapter.manga.update(dict(last_read=datetime.datetime.now()))

            if index is None:
                index = self.chapter.last_page_read_index or 0
            elif index == 'first':
                index = 0
            elif index == 'last':
                index = len(self.chapter.pages) - 1

            self.hide_spinner()
            self.render_page(index)

        if index is None:
            # We come from library
            self.image.clear()
        self.show_spinner()

        self.chapter = chapter

        thread = threading.Thread(target=run)
        thread.daemon = True
        thread.start()

    def on_button_press(self, widget, event):
        if event.type == Gdk.EventType.BUTTON_PRESS and event.button == 1:
            if event.x < self.size.width / 3:
                # 1st third of the page
                index = self.page_index + 1
            elif event.x > 2 * self.size.width / 3:
                # Last third of the page
                index = self.page_index - 1
            else:
                # Center: no action yet
                return

            if index >= 0 and index < len(self.chapter.pages):
                self.render_page(index)
            elif index == -1:
                # Get previous chapter
                db_conn = create_db_connection()
                row = db_conn.execute(
                    'SELECT id FROM chapters WHERE manga_id = ? AND rank = ?', (self.chapter.manga_id, self.chapter.rank - 1)).fetchone()
                db_conn.close()

                if row:
                    self.init(Chapter(row['id']), 'last')
            elif index == len(self.chapter.pages):
                # Get next chapter
                db_conn = create_db_connection()
                row = db_conn.execute(
                    'SELECT id FROM chapters WHERE manga_id = ? AND rank = ?', (self.chapter.manga_id, self.chapter.rank + 1)).fetchone()
                db_conn.close()

                if row:
                    self.init(Chapter(row['id']), 'first')

    def on_resize(self, window):
        size = self.viewport.get_allocated_size()[0]

        if self.size and (size.width != self.size.width or size.height != self.size.height):
            self.size = size
            self.set_page_image_from_pixbuf()

    def render_page(self, index):
        def get_page_image_path():
            page_path = self.chapter.get_page(self.page_index)

            GLib.idle_add(show_page_image, page_path)

        def show_page_image(page_path):
            if page_path:
                self.pixbuf = Pixbuf.new_from_file(page_path)
            else:
                self.pixbuf = Pixbuf.new_from_resource_at_scale('/com/gitlab/valos/MangaScan/images/missing_file.png', 180, -1, True)

            self.size = self.viewport.get_allocated_size()[0]
            self.set_page_image_from_pixbuf()

            self.image.show()

            self.hide_spinner()

            return False

        print('{0} {1}/{2}'.format(self.chapter.title, index + 1, len(self.chapter.pages) if self.chapter.pages else '?'))

        self.page_index = index
        self.chapter.update(dict(last_page_read_index=index))

        self.show_spinner()

        thread = threading.Thread(target=get_page_image_path)
        thread.daemon = True
        thread.start()

    def set_page_image_from_pixbuf(self):
        width = self.pixbuf.get_width()
        height = self.pixbuf.get_height()

        # Adjust image on width
        pixbuf = self.pixbuf.scale_simple(
            self.size.width,
            height / (width / self.size.width),
            InterpType.BILINEAR
        )
        self.image.set_from_pixbuf(pixbuf)

    def show_spinner(self):
        self.spinner_box.get_children()[0].start()
        self.spinner_box.show()
