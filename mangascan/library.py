from gi.repository import Gtk
from gi.repository.GdkPixbuf import Pixbuf

from mangascan.model import create_db_connection
from mangascan.model import Manga


class Library():
    def __init__(self, window):
        self.window = window
        self.builder = window.builder

        self.flowbox = self.builder.get_object('library_page_flowbox')
        self.flowbox.connect("child-activated", self.on_manga_clicked)
        self.flowbox.set_sort_func(self.sort)

        self.populate()

    def add_manga(self, manga, position=-1):
        cover_image = Gtk.Image()
        pixbuf = Pixbuf.new_from_file_at_scale(manga.cover_path, 180, -1, True)
        cover_image.set_from_pixbuf(pixbuf)
        cover_image.manga = manga
        cover_image.show()

        self.flowbox.insert(cover_image, position)

    def on_manga_added(self, manga):
        """
        Called from 'Add dialog' when user clicks on + button
        """
        db_conn = create_db_connection()
        nb_mangas = db_conn.execute('SELECT count(*) FROM mangas').fetchone()[0]
        db_conn.close()

        if nb_mangas == 1:
            # Library was previously empty
            self.populate()
        else:
            self.add_manga(manga)

    def on_manga_clicked(self, flowbox, child):
        self.window.card.populate(child.get_children()[0].manga)
        self.window.card.show()

    def on_manga_deleted(self, manga):
        # Remove manga cover in flowbox
        for child in self.flowbox.get_children():
            if child.get_children()[0].manga == manga:
                child.destroy()
                break

    def populate(self):
        db_conn = create_db_connection()
        mangas_rows = db_conn.execute('SELECT * FROM mangas ORDER BY last_read DESC').fetchall()

        if len(mangas_rows) == 0:
            if self.window.stack.is_ancestor(self.window):
                self.window.remove(self.window.stack)

            # Display first start message
            self.window.add(self.window.first_start_grid)

            return

        if self.window.first_start_grid.is_ancestor(self.window):
            self.window.remove(self.window.first_start_grid)

        self.window.add(self.window.stack)

        # Clear library flowbox
        for child in self.flowbox.get_children():
            self.flowbox.remove(child)
            child.destroy()

        # Populate flowbox with mangas covers
        for row in mangas_rows:
            self.add_manga(Manga(row['id']))

        db_conn.close()

        self.flowbox.show_all()

    def show(self):
        self.window.headerbar.set_title('Manga Scan')
        self.builder.get_object('menubutton').set_popover(self.builder.get_object('menubutton_popover'))

        self.window.show_page('library')

    def sort(self, child1, child2):
        manga1 = child1.get_children()[0].manga
        manga2 = child2.get_children()[0].manga

        # TODO: improve me
        if manga1.last_read is not None and manga2.last_read is not None:
            if manga1.last_read > manga2.last_read:
                return -1
            elif manga1.last_read < manga2.last_read:
                return 1
            else:
                return 0

        if manga1.last_read:
            return -1
        else:
            return 1